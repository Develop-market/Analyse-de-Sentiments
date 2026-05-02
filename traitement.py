"""
Analyse de sentiment & ABSA des commentaires Facebook bancaires
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mise à jour mars 2026 :
  - Modèle principal : cardiffnlp/camembert-base-tweet-sentiment-fr
    → Fine-tuné sur des tweets FR (plus proche du langage Facebook)
    → Labels : POSITIVE / NEGATIVE / NEUTRAL (3 classes, vs 2 avant)
  - Fallback léger : cmarkea/distilcamembert-base-sentiment
    → DistilCamemBERT, ~2× plus rapide pour la production
  - Inférence par batch (pipeline) — suppression de la boucle commentaire par commentaire
  - Gestion GPU automatique (device=0 si CUDA disponible)
  - Normalisation des labels robuste (insensible aux variantes de casse)
  - ABSA : détection multi-aspects par phrase (inchangé dans la logique)
  - Wordcloud : stopwords enrichis, filtre longueur amélioré
"""

import re
import json
import warnings
import pandas as pd
import torch
import torch.nn.functional as F
import nltk
import spacy

from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    pipeline,
)
from wordcloud import WordCloud
from nltk.corpus import stopwords
from unidecode import unidecode

warnings.filterwarnings("ignore", category=UserWarning)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# Modèle principal 2026 : fine-tuné sur tweets FR → adapté aux commentaires sociaux
MODEL_NAME = "cardiffnlp/camembert-base-tweet-sentiment-fr"

# Fallback plus léger (décommenter si RAM limitée)
# MODEL_NAME = "cmarkea/distilcamembert-base-sentiment"

BATCH_SIZE = 32           # Taille de batch pour l'inférence (adapter à la VRAM)
MAX_LENGTH = 512          # Longueur max des tokens
DEVICE = 0 if torch.cuda.is_available() else -1   # GPU si dispo, sinon CPU

INPUT_FILE_COMMENTS = "facebook_commentaires_concatene.csv"
INPUT_FILE_POSTS = "postes.csv"
OUTPUT_SENTIMENTS = "resultats_sentiments.csv"
OUTPUT_ABSA = "absa_df.csv"
OUTPUT_KPIS = "kpis.json"
OUTPUT_WORDCLOUD = "wordcloud.png"

# ─────────────────────────────────────────────
# STOPWORDS
# ─────────────────────────────────────────────
nltk.download("stopwords", quiet=True)
# python -m spacy download fr_core_news_md
nlp = spacy.load("fr_core_news_md")

_base_stop = set(stopwords.words("french"))
_custom_stop = {
    # Entités bancaires
    "banque", "côte", "ivoire", "services", "société", "générale", "écobank",
    "sgbci", "ecobank", "nsia", "bni", "sgci", "générale",
    # Termes génériques parasites
    "avis", "commentaires", "information", "dinformation", "bonjour", "bonne",
    "voir", "plus", "peu", "temps", "souvent", "encore", "aussi", "nationale",
    "investissement", "clients", "client", "merci", "svp", "alors", "alors",
    "voir plus", "en voir plus", "...",
    # Mots grammaticaux non couverts par NLTK
    "nos", "vos", "gens", "depuis", "hein", "puis", "moin", "meme", "cette",
    "compte", "deja", "ans", "ville", "année", "être", "matin", "jour", "bas",
    "petit", "quoi", "dire", "plateau", "reçu", "attend", "passer", "donner",
    "appeler", "combien", "vraiment", "semaine", "toujour", "vais", "chez",
    "savoir", "avant", "selon", "dites", "moins", "autres", "allez", "mettre",
    "toujours", "veux", "peux", "seulement", "créer", "revoyez","faire", "fait","jusqu","sans","quand","donc","franchement",
    "comment","comme","arrive","arrivé","arrivent","arrivent","arriver","arrivée","arrivés","arrivées","arrivons","arrivez","arrivent","arrivent","arrivera","arriveront"
}
STOP_WORDS = _base_stop | _custom_stop

# ─────────────────────────────────────────────
# MOTS-CLÉS NÉGATIFS (règle heuristique rapide)
# ─────────────────────────────────────────────
NEGATIVE_KEYWORDS = {
    "nul", "horrible", "détestable", "mauvais", "pourri", "pire", "décevant",
    "difficile", "compliqué", "pff", "souffre", "souffrance", "souffrent",
    "triste", "prelevement", "revoyez", "revoyer",
}

# ─────────────────────────────────────────────
# ASPECTS ABSA
# ─────────────────────────────────────────────
ASPECTS_CIBLES = {
    "application":    ["application", "appli", "mobile", "sg connect", "sgconnect"],
    "carte":          ["carte bancaire", "carte visa", "carte"],
    "frais":          ["frais", "coût", "tarif", "commission", "agio", "agios", "prelevements"],
    "guichet":        ["guichet", "gab", "guichet automatique","dab","distributeur"],
    "retrait":        ["retrait", "retrait d'argent", "retrait argent","retrait cash","caisse"],
    "gestionnaire":   ["gestionnaire", "conseiller", "conseillère", "conseillers", "conseillères", "conseil"],
    "prêt":           ["prêt", "emprunt", "crédit", "emprunter", "ppo","financement","financer","pret"],
    "agence":         ["agence", "locaux", "bureau","agences","siege","siège", "agence centrale","agence principale","banque privée"],
    "virement":       ["virement", "salaire","transfert", "transferts","virements","transfert d'argent","transfert argent","transactions","transaction"],
    "assurance":      ["assurance", "assurer","assurances","assuré","assurée","assurés","assurées","assureur","assureurs"],
    "service client": ["centre de relation client","crc", "client", "yeri", "service client", "service clientèle", "service clients", "service clientèle", "support", "assistance"],
}


# ─────────────────────────────────────────────
# CHARGEMENT DU MODÈLE
# ─────────────────────────────────────────────
def load_model():
    """
    Charge le tokenizer et le modèle de sentiment.
    2026 : cardiffnlp/camembert-base-tweet-sentiment-fr
    → 3 labels : POSITIVE / NEGATIVE / NEUTRAL
    → Fine-tuné sur des tweets FR, plus adapté aux réseaux sociaux
    """
    print(f"🤖 Chargement du modèle : {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    print(f"✅ Labels disponibles : {model.config.id2label}")
    return tokenizer, model


tokenizer, model = load_model()

# Pipeline Hugging Face avec inférence par batch et gestion GPU
analyseur_sentiment = pipeline(
    "sentiment-analysis",
    model=model,
    tokenizer=tokenizer,
    device=DEVICE,
    batch_size=BATCH_SIZE,
    truncation=True,
    max_length=MAX_LENGTH,
    padding=True,
)


# ─────────────────────────────────────────────
# NORMALISATION DES LABELS
# ─────────────────────────────────────────────
def normaliser_label(label: str) -> str:
    """
    Normalise les variantes de labels selon le modèle utilisé.
    cardiffnlp → "positive" / "negative" / "neutral"
    cmarkea   → "POSITIVE" / "NEGATIVE" (5 étoiles → 2 classes)
    Retourne toujours POSITIVE / NEGATIVE / NEUTRAL en majuscules.
    """
    label_lower = label.lower()
    if "pos" in label_lower:
        return "POSITIVE"
    if "neg" in label_lower:
        return "NEGATIVE"
    return "NEUTRAL"


# ─────────────────────────────────────────────
# FLAG SENTIMENT (degré + polarité)
# ─────────────────────────────────────────────
def _calculer_flag(prob_pos: float, prob_neg: float, prob_neu: float) -> tuple[str, str]:
    """
    Calcule :
      - flag    : label de degré (ex. 'Très négatif', 'Positif', 'Neutre')
      - gravite : alias négatif rétrocompatible (utilisé par app.py)

    Seuils négatifs  : ≥0.80 Très négatif | ≥0.55 Négatif | ≥0.30 Légèrement négatif
    Seuils positifs  : ≥0.80 Très positif  | ≥0.55 Positif  | ≥0.30 Légèrement positif
    Neutre           : tout le reste
    """
    if prob_neg >= 0.80:
        return "Très négatif",          "Très critique"
    elif prob_neg >= 0.55:
        return "Négatif",               "Critique"
    elif prob_neg >= 0.30:
        return "Légèrement négatif",    "Modéré"
    elif prob_pos >= 0.80:
        return "Très positif",          "Aucune"
    elif prob_pos >= 0.55:
        return "Positif",               "Aucune"
    elif prob_pos >= 0.30:
        return "Légèrement positif",    "Aucune"
    else:
        return "Neutre",                "Aucune"


# ─────────────────────────────────────────────
# PRÉDICTION DE SENTIMENT
# ─────────────────────────────────────────────
def predict_sentiment(texts: list[str]) -> list[dict]:
    """
    Prédit le sentiment d'une liste de textes par batch.

    Logique :
    1. Heuristique rapide : si un mot-clé négatif fort est présent → NEGATIVE direct
    2. Sinon → modèle Transformer avec top_k=None (toutes les proba)

    Retourne : liste de dicts avec :
      label         — classe dominante (POSITIVE / NEGATIVE / NEUTRAL)
      score         — confiance de la classe dominante
      prob_positive — probabilité positive
      prob_negative — probabilité négative
      prob_neutral  — probabilité neutre
      flag          — degré de sentiment (ex. 'Très négatif', 'Positif', 'Neutre')
      gravite       — alias négatif rétrocompatible (Très critique / Critique / Modéré / Aucune)
    """
    results = []
    indices_to_model = []
    texts_to_model = []

    # Passe 1 : heuristique rapide (mot-clé négatif fort détecté)
    for i, text in enumerate(texts):
        text_lower = text.lower()
        if any(kw in text_lower for kw in NEGATIVE_KEYWORDS):
            results.append({
                "label":        "NEGATIVE",
                "score":        1.0,
                "prob_positive": 0.0,
                "prob_negative": 1.0,
                "prob_neutral":  0.0,
                "flag":         "Très négatif",
                "gravite":      "Très critique",
            })
        else:
            results.append(None)
            indices_to_model.append(i)
            texts_to_model.append(text)

    # Passe 2 : inférence batch avec toutes les probabilités
    if texts_to_model:
        print(f"  🔮 Inférence sur {len(texts_to_model)} textes "
              f"(batch={BATCH_SIZE}, device={'GPU' if DEVICE == 0 else 'CPU'})...")
        try:
            predictions = analyseur_sentiment(texts_to_model, top_k=None)
            for idx, pred_list in zip(indices_to_model, predictions):
                prob_pos = prob_neg = prob_neu = 0.0
                best_label, best_score = None, -1.0

                for p in pred_list:
                    norm = normaliser_label(p["label"])
                    if norm == "POSITIVE":  prob_pos = p["score"]
                    elif norm == "NEGATIVE": prob_neg = p["score"]
                    elif norm == "NEUTRAL":  prob_neu = p["score"]
                    if p["score"] > best_score:
                        best_score, best_label = p["score"], norm

                flag, gravite = _calculer_flag(prob_pos, prob_neg, prob_neu)
                results[idx] = {
                    "label":         best_label,
                    "score":         round(best_score, 4),
                    "prob_positive": round(prob_pos, 4),
                    "prob_negative": round(prob_neg, 4),
                    "prob_neutral":  round(prob_neu, 4),
                    "flag":          flag,
                    "gravite":       gravite,
                }
        except Exception as e:
            print(f"  ⚠️ Erreur inférence batch : {e} — fallback NEUTRAL")
            for idx in indices_to_model:
                if results[idx] is None:
                    results[idx] = {
                        "label":         "NEUTRAL",
                        "score":         0.5,
                        "prob_positive": 0.0,
                        "prob_negative": 0.0,
                        "prob_neutral":  1.0,
                        "flag":          "Neutre",
                        "gravite":       "Aucune",
                    }

    return results

# ─────────────────────────────────────────────
# NETTOYAGE DE TEXTE
# ─────────────────────────────────────────────
def nettoyer_texte(texte: str) -> str:
    """Nettoyage de base : minuscules, sans accents, sans ponctuation"""
    texte = str(texte).lower()
    texte = unidecode(texte)
    texte = re.sub(r"http\S+", "", texte)
    texte = re.sub(r"[^\w\s]", " ", texte)
    texte = re.sub(r"\s+", " ", texte)
    return texte.strip()


def clean_text_for_wordcloud(texte: str) -> str:
    """Nettoyage + filtrage stopwords pour le wordcloud"""
    texte = nettoyer_texte(texte)
    mots = [m for m in texte.split() if m not in STOP_WORDS and len(m) > 2]
    return " ".join(mots)


# ─────────────────────────────────────────────
# NORMALISATION DES TEXTES POUR ABSA
# ─────────────────────────────────────────────
def normaliser_texte_absa(texte: str) -> str:
    """Supprime les accents + nettoyage minimal pour la correspondance d'aspects"""
    texte = texte.lower()
    for pattern, repl in [
        (r"[éèêë]", "e"), (r"[àâä]", "a"), (r"[îï]", "i"),
        (r"[ôö]", "o"),   (r"[ùûü]", "u"),
    ]:
        texte = re.sub(pattern, repl, texte)
    texte = re.sub(r"[^a-z0-9\s']", " ", texte)
    return texte


# ─────────────────────────────────────────────
# ANALYSE ABSA (Aspect-Based Sentiment Analysis)
# ─────────────────────────────────────────────
def analyse_absa(texte: str) -> list[tuple]:
    """
    Détecte les aspects mentionnés dans chaque phrase et leur sentiment.
    Retourne : liste de (aspect, phrase, sentiment)
    """
    doc = nlp(texte)
    resultats = []

    phrases = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    if not phrases:
        return []

    # Détecter les aspects pour chaque phrase
    phrases_avec_aspects = []
    for phrase in phrases:
        phrase_norm = normaliser_texte_absa(phrase)
        aspects_detectes = set()
        for aspect, expressions in ASPECTS_CIBLES.items():
            for exp in expressions:
                if exp in phrase_norm:
                    aspects_detectes.add(aspect)
                    break
        if aspects_detectes:
            phrases_avec_aspects.append((phrase, aspects_detectes))

    if not phrases_avec_aspects:
        return []

    # Inférence de sentiment sur les phrases filtrées (batch)
    phrases_seules = [p for p, _ in phrases_avec_aspects]
    try:
        predictions = analyseur_sentiment(phrases_seules, top_k=None)
    except Exception as e:
        print(f"  ⚠️ Erreur ABSA inférence : {e}")
        return []

    for (phrase, aspects), pred_list in zip(phrases_avec_aspects, predictions):
        # Trouver le label avec le score le plus élevé
        best = max(pred_list, key=lambda p: p["score"])
        label = normaliser_label(best["label"])
        if "pos" in label.lower():
            sentiment = "positif"
        elif "neg" in label.lower():
            sentiment = "negatif"
        else:
            sentiment = "neutre"

        for aspect in aspects:
            resultats.append((aspect, phrase, sentiment))

    return resultats


# ─────────────────────────────────────────────
# WORDCLOUD
# ─────────────────────────────────────────────
def generate_wordcloud(
    df: pd.DataFrame,
    bank_filter: str = "sgci",
    phrase_col: str = "phrase",
    source_col: str = "source",
    sentiment_filter: str = "negatif",
    output_path: str = OUTPUT_WORDCLOUD,
):
    """
    Génère un wordcloud pour les phrases négatives d'une banque donnée.
    """
    mask = df[source_col].str.contains(bank_filter, case=False, na=False)
    if sentiment_filter:
        mask &= df["sentiment"].str.lower() == sentiment_filter

    bank_df = df[mask]

    if bank_df.empty:
        print(f"⚠️ Aucune donnée pour '{bank_filter}' ({sentiment_filter}) — wordcloud ignoré")
        return

    texte_final = " ".join(
        clean_text_for_wordcloud(phrase)
        for phrase in bank_df[phrase_col].dropna()
    )

    if not texte_final.strip():
        print("⚠️ Texte vide après nettoyage — wordcloud ignoré")
        return

    wc = WordCloud(
        width=1200,
        height=600,
        background_color="white",
        max_words=150,
        collocations=False,     # évite les doublons de bi-grammes
        min_word_length=3,
    ).generate(texte_final)
    wc.to_file(output_path)
    print(f"✅ Wordcloud sauvegardé : {output_path}")


# ─────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────
def process_data(
    path_concatene: str = INPUT_FILE_COMMENTS,
    path_postes: str = INPUT_FILE_POSTS,
):
    print("🚀 Démarrage du pipeline NLP...\n")

    # ── Chargement ─────────────────────────────────────────────────
    df = pd.read_csv(path_concatene)
    df_postes = pd.read_csv(path_postes)

    # ── Prétraitement ──────────────────────────────────────────────
    df.columns = df.columns.str.lower()
    df = df[["date", "auteur", "commentaire", "source"]].dropna()
    df["commentaire"] = df["commentaire"].astype(str).str.replace(r"\\n", " ", regex=True)
    df["ts"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["ts"])
    df = df[df["commentaire"].str.strip() != ""]
    df = df.drop_duplicates(subset=["auteur", "commentaire"])
    print(f"📊 {len(df)} commentaires à analyser")

    # ── Prédiction sentiment (batch) ───────────────────────────────
    print("\n🔮 Analyse de sentiment...")
    sentiments = predict_sentiment(df["commentaire"].tolist())
    df["sentiment"]     = [s["label"]         for s in sentiments]
    df["score"]         = [s["score"]         for s in sentiments]
    df["prob_positive"] = [s["prob_positive"]  for s in sentiments]
    df["prob_negative"] = [s["prob_negative"]  for s in sentiments]
    df["prob_neutral"]  = [s["prob_neutral"]   for s in sentiments]
    df["flag"]          = [s["flag"]           for s in sentiments]
    df["gravite"]       = [s["gravite"]        for s in sentiments]
    df["date"]          = df["ts"]

    # ── ABSA ───────────────────────────────────────────────────────
    print("\n🔍 Analyse ABSA (aspects)...")
    df["clean"] = df["commentaire"].astype(str).apply(nettoyer_texte)

    analyse_finale = []
    for _, row in df.iterrows():
        aspects = analyse_absa(row["clean"])
        for aspect, phrase, sentiment in aspects:
            analyse_finale.append({
                "source":        row["source"],
                "auteur":        row["auteur"],
                "date":          row["date"],
                "phrase":        phrase,
                "aspect":        aspect,
                "sentiment":     sentiment,
                "flag":          row.get("flag",          "Neutre"),
                "gravite":       row.get("gravite",       "Aucune"),
                "prob_negative": row.get("prob_negative", 0.0),
                "prob_positive": row.get("prob_positive", 0.0),
                "prob_neutral":  row.get("prob_neutral",  0.0),
            })

    # ── KPIs ───────────────────────────────────────────────────────
    kpis = {
        "total_comments":           int(len(df)),
        "positive_comments":        int((df["sentiment"] == "POSITIVE").sum()),
        "negative_comments":        int((df["sentiment"] == "NEGATIVE").sum()),
        "neutral_comments":         int((df["sentiment"] == "NEUTRAL").sum()),
        "pct_positive":             round((df["sentiment"] == "POSITIVE").mean() * 100, 1),
        "pct_negative":             round((df["sentiment"] == "NEGATIVE").mean() * 100, 1),
        # Répartition par flag (tous sentiments, par degré)
        "flag_tres_negatif":        int((df["flag"] == "Très négatif").sum()),
        "flag_negatif":             int((df["flag"] == "Négatif").sum()),
        "flag_legerement_negatif":  int((df["flag"] == "Légèrement négatif").sum()),
        "flag_neutre":              int((df["flag"] == "Neutre").sum()),
        "flag_legerement_positif":  int((df["flag"] == "Légèrement positif").sum()),
        "flag_positif":             int((df["flag"] == "Positif").sum()),
        "flag_tres_positif":        int((df["flag"] == "Très positif").sum()),
        # Alias rétrocompatible (flag négatif → gravite)
        "gravite_tres_critique":    int((df["gravite"] == "Très critique").sum()),
        "gravite_critique":         int((df["gravite"] == "Critique").sum()),
        "gravite_moderee":          int((df["gravite"] == "Modéré").sum()),
        "gravite_aucune":           int((df["gravite"] == "Aucune").sum()),
    }
    print(f"\n📈 KPIs : {kpis}")

    # ── Sauvegardes ────────────────────────────────────────────────
    df.to_csv(OUTPUT_SENTIMENTS, index=False, encoding="utf-8-sig")
    print(f"✅ Sentiments sauvegardés : {OUTPUT_SENTIMENTS}")

    df_postes.to_csv(path_postes, index=False, encoding="utf-8-sig")

    with open(OUTPUT_KPIS, "w", encoding="utf-8") as f:
        json.dump(kpis, f, ensure_ascii=False, indent=2)
    print(f"✅ KPIs sauvegardés : {OUTPUT_KPIS}")

    absa_df = pd.DataFrame(analyse_finale).drop_duplicates()
    absa_df.to_csv(OUTPUT_ABSA, index=False, encoding="utf-8-sig")
    print(f"✅ ABSA sauvegardé : {OUTPUT_ABSA} ({len(absa_df)} lignes)")

    # ── Wordcloud ──────────────────────────────────────────────────
    generate_wordcloud(absa_df, bank_filter="sgci", output_path=OUTPUT_WORDCLOUD)

    print("\n✅ Pipeline NLP terminé !")
    return df, absa_df, kpis


# ─────────────────────────────────────────────
if __name__ == "__main__":
    process_data()
