
import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from wordcloud import WordCloud
import torch.nn.functional as F
from nltk.corpus import stopwords
import nltk
import re
import spacy
from unidecode import unidecode
import json
from transformers import pipeline


# Télécharger les stopwords français
nltk.download('stopwords')
nlp = spacy.load("fr_core_news_md")
stop_words = set(stopwords.words('french'))
custom_stopwords = {
    "banque", "côte", "d'", "ivoire", "services", "société générale", "écobank", "générale", "dinformation", "information",
    "avis", "ivoire", "commentaires", "sgbci", "ecobank", "nsia", "bni",
    "bonne", "bonjour", "voir plus", "peu", "temps", "souvent",
    "société", "encore", "aussi", "voir", "en voir plus", "... en voir plus", "...", "d", "plus", "nationale", "d investissement"
}
stop_words.update(custom_stopwords)


def load_model():
    model_name = "philschmid/pt-tblard-tf-allocine"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    return tokenizer, model


tokenizer, model = load_model()
labels = model.config.id2label

# def predict_sentiment(texts, tokenizer, model):
#     labels = model.config.id2label
#     results = []
#     for text in texts:
#         inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
#         with torch.no_grad():
#             logits = model(**inputs).logits
#             probs = F.softmax(logits, dim=-1)[0]
#             idx = torch.argmax(probs).item()
#             results.append({'label': labels[idx], 'score': float(probs[idx])})
#     return results

negative_keywords = {"nul", "horrible", "détestable", "mauvais", "pourri", "pire", "décevant","difficile","pourquoi","compliqué","mais","longue","pff","souffre","souffrance","souffrent",
                     "triste","prelevement","revoyez","revoyer", "pas"}


def predict_sentiment(texts, tokenizer, model):
    labels = model.config.id2label
    results = []

    for text in texts:
        text_lower = text.lower()
        contains_negative = any(word in text_lower for word in negative_keywords)

        if contains_negative:
            results.append({'label': 'NEGATIVE', 'score': 1.0})
        else:
            inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                logits = model(**inputs).logits
                probs = F.softmax(logits, dim=-1)[0]
                idx = torch.argmax(probs).item()
                results.append({'label': labels[idx], 'score': float(probs[idx])})

    return results


def clean_text(text):
    text = text.lower()
    text = re.sub(r'[^a-zA-ZÀ-ÿ\\s]', '', text)
    words = text.split()
    words = [w for w in words if w not in stop_words and len(w) > 2]
    return ' '.join(words)


def nettoyer_textes(text):
    # Nettoyage de base (à adapter si besoin)
    text = re.sub(r"[^\w\s]", " ", str(text).lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def nettoyer_texte(texte):
    texte = texte.lower()
    texte = unidecode(texte)
    texte = re.sub(r"http\S+", "", texte)
    texte = re.sub(r"[^\w\s]", " ", texte)
    texte = re.sub(r"\s+", " ", texte)
    return texte.strip()


def generate_wordcsloud(series, output_path="wordcloud.png"):
    text_all = ' '.join([clean_text(t) for t in series.dropna()])
    wc = WordCloud(width=800, height=400, background_color='white').generate(text_all)
    wc.to_file(output_path)

analyseur_sentiment = pipeline("sentiment-analysis", model=model, tokenizer=tokenizer)
aspects_cibles = ['gestionnaire', 'application', 'frais', 'carte', 'guichet', 'retrait', 'prêt', 'agence', 'virement',"assurance","service"]

# # Analyseur de sentiment
# analyseur_sentiment = pipeline("sentiment-analysis", model=model, tokenizer=tokenizer)

# Dictionnaire d’aspects avec leurs expressions clés associées
aspects_cibles = {
    'application': ['application', 'appli', 'mobile', 'sg connect'],
    'carte': ['carte bancaire', 'carte visa', 'carte'],
    'frais': ['frais', 'coût', 'tarif', 'commission','agio','agios',"prelevements"],
    'guichet': ['guichet', 'gab', 'guichet automatique'],
    'retrait': ['retrait', 'retrait d\'argent'],
    'gestionnaire': ['gestionnaire', 'conseiller'],
    'prêt': ['prêt', 'emprunt', 'crédit',"emprunter"],
    'agence': ['agence', 'locaux', 'bureau'],
    'virement': ['virement','salaire'],
    'assurance': ['assurance', 'assurer'],
    'service client': ['service', 'client', 'yeri']
}

def normaliser_texte(texte):
    """Minuscule + sans accents + nettoyage basique"""
    texte = texte.lower()
    texte = re.sub(r"[éèêë]", "e", texte)
    texte = re.sub(r"[àâä]", "a", texte)
    texte = re.sub(r"[îï]", "i", texte)
    texte = re.sub(r"[ôö]", "o", texte)
    texte = re.sub(r"[ùûü]", "u", texte)
    texte = re.sub(r"[^a-z0-9\s']", " ", texte)
    return texte

# def analyse_absa(texte):
#     doc = nlp(texte)
#     resultats = []

#     for sent in doc.sents:
#         phrase = sent.text.strip()
#         phrase_norm = normaliser_texte(phrase)
#         aspect_trouve = None

#         for aspect, expressions in aspects_cibles.items():
#             for exp in expressions:
#                 if exp in phrase_norm:
#                     aspect_trouve = aspect
#                     break
#             if aspect_trouve:
#                 break

#         if not aspect_trouve:
#             continue  # ⛔ Ignore la phrase si aucun aspect détecté

#         try:
#             prediction = analyseur_sentiment(phrase)[0]
#             label = prediction['label'].lower()

#             if 'pos' in label:
#                 sentiment = "positif"
#             elif 'neg' in label:
#                 sentiment = "negatif"
#             else:
#                 sentiment = "neutre"

#             resultats.append((aspect_trouve, phrase, sentiment))
#         except:
#             continue

#     return resultats
def analyse_absa(texte):
    doc = nlp(texte)
    resultats = []

    for sent in doc.sents:
        phrase = sent.text.strip()
        phrase_norm = normaliser_texte(phrase)

        aspects_detectes = set()
        for aspect, expressions in aspects_cibles.items():
            for exp in expressions:
                if exp in phrase_norm:
                    aspects_detectes.add(aspect)
                    break  # Une fois une expression trouvée pour un aspect, on le note et on passe au suivant

        if not aspects_detectes:
            continue  # ⛔ Ignore la phrase si aucun aspect détecté

        # Analyse de sentiment pour toute la phrase
        try:
            prediction = analyseur_sentiment(phrase)[0]
            label = prediction['label'].lower()

            if 'pos' in label:
                sentiment = "positif"
            elif 'neg' in label:
                sentiment = "negatif"
            else:
                sentiment = "neutre"

            # Associer chaque aspect détecté à cette phrase et ce sentiment
            for aspect in aspects_detectes:
                resultats.append((aspect, phrase, sentiment))
        except:  # noqa: E722
            continue

    return resultats



# Supposons que stop_words (de nltk) est déjà importé
french_stop_words = stop_words.union([
    "alors", "voir plus", "voir", "aussi", "autre", "avec", "avoir", "bon", "car", "ce", "cela", "ces", "ceux",
    "chaque", "ci", "comme", "comment", "dans", "des", "du", "dedans", "dehors", "depuis", "devrait", "doit",
    "donc", "elle", "elles", "en", "encore", "essai", "est", "et", "eu", "fait", "faites", "fois", "font","seulement","créer","deja","svp","ans","ville","année","revoyez","être","matin","jour","bas",
    "ici", "il", "ils", "je", "juste", "la", "le", "les", "leur", "là", "ma", "maintenant", "mais", "mes","petit","quoi","dire","plateau","reçu","attend","passer","donner","appeler",
    "mon", "mot", "ni", "notre", "nous", "ou", "où", "par", "parce", "pas", "peut", "peu", "pour", "pourquoi","combien","vraiment","semaine","toujour","vais",
    "quand", "que", "quel", "quelle", "quelles", "quels", "qui", "sa", "sans", "ses", "si", "son", "sont","chez","savoir","avant","selon","dites","moins","autres",
    "sur", "ta", "tandis", "tellement", "tels", "tes", "ton", "tous", "tout", "très", "tu", "votre", "vous", "vu",
    "banque", "côte", "d'", "ivoire", "services", "société", "générale", "écobank", "dinformation", "information","allez","mettre","clients","toujours",
    "avis", "commentaires", "sgbci", "ecobank", "nsia", "bni", "bonne", "bonjour", "temps", "souvent","veux","peux","merci","client","sgci",
    "encore", "voir", "...", "d", "plus", "nationale", "d investissement",'nos',"vos","gens","depuis","hein","puis","moin","meme","cette","compte"
])


def generate_wordcloud(df, bank_filter="sgci", phrase_col="phrase", source_col="source", output_path="wordcloud.png"):
    """
    Génère un wordcloud pour les phrases associées à une banque spécifique.
    
    Paramètres :
    - df : DataFrame contenant les commentaires
    - bank_filter : chaîne pour filtrer la colonne source
    - phrase_col : nom de la colonne contenant les phrases
    - source_col : nom de la colonne contenant la source
    - output_path : chemin de sauvegarde de l'image PNG
    """
    # Filtrage des phrases liées à la banque choisie
    bank_df = df[df[source_col].str.contains(bank_filter, case=False, na=False)]
    bank_df = bank_df[bank_df["sentiment"]=="negatif"]

    if bank_df.empty:
        print(f"Aucune donnée trouvée pour la banque '{bank_filter}'.")
        return

    textes_propres = []
    for phrase in bank_df[phrase_col].dropna():
        texte_nettoye = nettoyer_texte(phrase)
        mots = texte_nettoye.split()
        mots_filtres = [mot for mot in mots if mot not in french_stop_words and len(mot) > 2]
        textes_propres.append(" ".join(mots_filtres))

    texte_final = " ".join(textes_propres)

    # Génération du wordcloud
    wc = WordCloud(width=800, height=400, background_color='white').generate(texte_final)
    wc.to_file(output_path)



def process_data(path_concatene="facebook_commentaires_concatene.csv", path_postes="postes.csv"):
    df = pd.read_csv(path_concatene)
    df_postes = pd.read_csv(path_postes)

    # Prétraitement
    df.columns = df.columns.str.lower()
    df = df[['date','auteur', 'commentaire', 'source']].dropna()
    df['commentaire'] = df['commentaire'].astype(str).str.replace("\\n", " ")
    df['ts'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['ts'])
    df = df[df['commentaire'].str.strip() != '']

    # Chargement du modèle et prédiction
    tokenizer, model = load_model()
    sentiments = predict_sentiment(df['commentaire'].tolist(), tokenizer, model)
    df['sentiment'] = [s['label'] for s in sentiments]
    df['score'] = [s['score'] for s in sentiments]
    df['date'] = df['ts']

    df['clean'] = df['commentaire'].astype(str).apply(nettoyer_texte)
    analyse_finale = []
    for _, row in df.iterrows():
        aspects = analyse_absa(row['clean'])
        date = row['date']
        for aspect, phrase, sentiment in aspects:
            analyse_finale.append({
            'source': row['source'],
            'auteur': row['auteur'],
                'date' : date,
                'phrase': phrase,
                'aspect': aspect,
                'sentiment': sentiment
            })
    # KPIs
    kpis = {
        'total_comments': len(df),
        'positive_comments': (df['sentiment'] == 'POSITIVE').sum(),
        'negative_comments': (df['sentiment'] == 'NEGATIVE').sum()
    }

    # Sauvegardes locales
    
    df.to_csv("resultats_sentiments.csv", index=False)
    df_postes.to_csv("postes.csv", index=False)
    with open("kpis.json", "w") as f:
        json.dump({k: int(v) for k, v in kpis.items()}, f)

    absa_df = pd.DataFrame(analyse_finale)
    absa_df = absa_df.drop_duplicates()
    absa_df.to_csv("absa_df.csv",index=False)
    generate_wordcloud(absa_df, bank_filter="sgci", output_path="wordcloud.png")
# Si exécuté directement
if __name__ == "__main__":
    process_data()
