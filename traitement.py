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
    "toujours", "veux", "peux", "seulement", "créer", "revoyez",
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
    "guichet":        ["guichet", "gab", "guichet automatique"],
    "retrait":        ["retrait", "retrait d'argent"],
    "gestionnaire":   ["gestionnaire", "conseiller"],
    "prêt":           ["prêt", "emprunt", "crédit", "emprunter"],
    "agence":         ["agence", "locaux", "bureau"],
    "virement":       ["virement", "salaire"],
    "assurance":      ["assurance", "assurer"],
    "service client": ["service", "client", "yeri"],
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
# PRÉDICTION DE SENTIMENT
# ─────────────────────────────────────────────
def predict_sentiment(texts: list[str]) -> list[dict]:
    """
    Prédit le sentiment d'une liste de textes par batch.

    Logique :
    1. Heuristique rapide : si un mot-clé négatif fort est présent → NEGATIVE direct
    2. Sinon → modèle Transformer (inférence par batch)

    Retourne : liste de {'label': str, 'score': float}
    """
    results = []
    indices_to_model = []   # indices des textes à envoyer au modèle
    texts_to_model = []

    # Passe 1 : heuristique rapide
    for i, text in enumerate(texts):
        text_lower = text.lower()
        if any(kw in text_lower for kw in NEGATIVE_KEYWORDS):
            results.append({"label": "NEGATIVE", "score": 1.0})
        else:
            results.append(None)           # placeholder
            indices_to_model.append(i)
            texts_to_model.append(text)

    # Passe 2 : inférence batch sur les textes restants
    if texts_to_model:
        print(f"  🔮 Inférence sur {len(texts_to_model)} textes (batch={BATCH_SIZE}, device={'GPU' if DEVICE == 0 else 'CPU'})...")
        try:
            predictions = analyseur_sentiment(texts_to_model)
            for idx, pred in zip(indices_to_model, predictions):
                results[idx] = {
                    "label": normaliser_label(pred["label"]),
                    "score": round(pred["score"], 4),
                }
        except Exception as e:
            print(f"  ⚠️ Erreur inférence batch : {e} — fallback NEUTRAL")
            for idx in indices_to_model:
                if results[idx] is None:
                    results[idx] = {"label": "NEUTRAL", "score": 0.5}

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
        predictions = analyseur_sentiment(phrases_seules)
    except Exception as e:
        print(f"  ⚠️ Erreur ABSA inférence : {e}")
        return []

    for (phrase, aspects), pred in zip(phrases_avec_aspects, predictions):
        label = normaliser_label(pred["label"])
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
    df["sentiment"] = [s["label"] for s in sentiments]
    df["score"] = [s["score"] for s in sentiments]
    df["date"] = df["ts"]

    # ── ABSA ───────────────────────────────────────────────────────
    print("\n🔍 Analyse ABSA (aspects)...")
    df["clean"] = df["commentaire"].astype(str).apply(nettoyer_texte)

    analyse_finale = []
    for _, row in df.iterrows():
        aspects = analyse_absa(row["clean"])
        for aspect, phrase, sentiment in aspects:
            analyse_finale.append({
                "source":   row["source"],
                "auteur":   row["auteur"],
                "date":     row["date"],
                "phrase":   phrase,
                "aspect":   aspect,
                "sentiment": sentiment,
            })

    # ── KPIs ───────────────────────────────────────────────────────
    kpis = {
        "total_comments":    int(len(df)),
        "positive_comments": int((df["sentiment"] == "POSITIVE").sum()),
        "negative_comments": int((df["sentiment"] == "NEGATIVE").sum()),
        "neutral_comments":  int((df["sentiment"] == "NEUTRAL").sum()),  # nouveau label 2026
        "pct_positive":      round((df["sentiment"] == "POSITIVE").mean() * 100, 1),
        "pct_negative":      round((df["sentiment"] == "NEGATIVE").mean() * 100, 1),
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
