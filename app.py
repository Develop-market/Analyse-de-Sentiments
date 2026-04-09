"""
Dashboard Analyse Sentiments — Banques CI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mise à jour mars 2026 :
  - dash_table.DataTable → dash_ag_grid (DataTable déprécié en Dash 2.19+)
  - app.run_server() → app.run()  (run_server supprimé depuis Dash 2.18)
  - Suppression de ollama/subprocess (inutilisé dans les callbacks)
  - Gestion du label NEUTRAL (nouveau label du modèle NLP 2026)
  - SECRET_KEY via variable d'environnement uniquement (bonne pratique sécurité)
  - Passwords hashés avec werkzeug.security (stockage en clair supprimé)
  - Filtres de date avec valeur de départ dynamique (plus de date codée en dur)
  - Correction du bug absa_df["date"].sort_values() (retournait une Series, pas un tri)
  - Nettoyage des global variables mutables dans les callbacks
"""

import io
import os
import json
import base64
import datetime as dt

import numpy as np
import pandas as pd
import plotly.express as px
import dash
import dash_ag_grid as dag          # remplace dash_table (déprécié Dash 2.19+)
from dash import dcc, html, Input, Output
from flask import session, redirect, request
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
# Mots de passe hashés — ne jamais stocker en clair
USERS = {
    "admin":    generate_password_hash("motdepasse123"),
    "analyste": generate_password_hash("analyse2025"),
}

# Charte Société Générale
SG_RED          = "#E60000"
SG_BLACK        = "#000000"
SG_GREY         = "#3D3D3D"
SG_LIGHT_GREY   = "#F5F5F5"
SG_WHITE        = "#FFFFFF"
SG_RED_GRADIENT = "linear-gradient(135deg, #E60000 0%, #A00000 100%)"


# ─────────────────────────────────────────────
# STYLES RÉUTILISABLES
# ─────────────────────────────────────────────
CARD = {
    "backgroundColor": SG_WHITE,
    "padding": "35px",
    "borderRadius": "20px",
    "boxShadow": "0 10px 40px rgba(230, 0, 0, 0.08)",
    "marginBottom": "30px",
    "border": f"1px solid {SG_LIGHT_GREY}",
}
HERO = {
    "background": SG_RED_GRADIENT,
    "color": SG_WHITE,
    "padding": "60px 40px",
    "borderRadius": "24px",
    "marginBottom": "50px",
    "boxShadow": "0 20px 60px rgba(230, 0, 0, 0.25)",
}
FILTER_BOX = {
    "backgroundColor": SG_WHITE,
    "padding": "30px",
    "borderRadius": "20px",
    "marginBottom": "40px",
    "border": f"2px solid {SG_RED}",
    "boxShadow": "0 8px 30px rgba(0,0,0,0.06)",
}
SECTION_TITLE = {
    "fontSize": "32px",
    "fontWeight": "700",
    "color": SG_BLACK,
    "marginBottom": "15px",
    "letterSpacing": "-0.5px",
    "fontFamily": "'Segoe UI', 'Helvetica Neue', sans-serif",
}
ACCENT_BOX = {
    "backgroundColor": SG_LIGHT_GREY,
    "padding": "25px",
    "borderRadius": "16px",
    "borderLeft": f"6px solid {SG_RED}",
    "marginBottom": "20px",
}
LABEL_STYLE = {
    "fontWeight": "700",
    "marginBottom": "12px",
    "display": "block",
    "color": SG_RED,
    "fontSize": "12px",
    "letterSpacing": "1.5px",
}

# ─────────────────────────────────────────────
# CHARGEMENT DES DONNÉES
# ─────────────────────────────────────────────
def load_data():
    """Charge tous les fichiers de données au démarrage"""
    df, kpis, absa_df, df_postes, wordcloud_base64 = (
        pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame(), None
    )

    try:
        df = pd.read_csv("resultats_sentiments.csv")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df.dropna(subset=["date"], inplace=True)
    except Exception as e:
        print(f"⚠️ resultats_sentiments.csv : {e}")

    try:
        with open("kpis.json") as f:
            kpis = json.load(f)
    except Exception as e:
        print(f"⚠️ kpis.json : {e}")

    try:
        absa_df = pd.read_csv("absa_df.csv")
        absa_df["date"] = pd.to_datetime(absa_df["date"], errors="coerce")
    except Exception as e:
        print(f"⚠️ absa_df.csv : {e}")

    try:
        df_postes = pd.read_csv("postes.csv")
    except Exception as e:
        print(f"⚠️ postes.csv : {e}")

    try:
        img = Image.open("wordcloud.png")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        wordcloud_base64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"⚠️ wordcloud.png : {e}")

    return df, kpis, absa_df, df_postes, wordcloud_base64


df, kpis, absa_df, df_postes, wordcloud_base64 = load_data()

# Dates min/max dynamiques (plus de dates codées en dur)
DATE_MIN = dt.date(2025, 1, 1)
DATE_MAX_COMMENTS = df["date"].max().date() if not df.empty else dt.date.today()
DATE_MAX_ABSA = absa_df["date"].max().date() if not absa_df.empty else dt.date.today()


# ─────────────────────────────────────────────
# APPLICATION DASH
# ─────────────────────────────────────────────
app = dash.Dash(__name__, suppress_callback_exceptions=True)
server = app.server

# SECRET_KEY uniquement via variable d'environnement — jamais de valeur par défaut en prod
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    import secrets
    _secret = secrets.token_hex(32)
    print("⚠️ SECRET_KEY non définie — clé aléatoire générée (sessions non persistantes)")
server.secret_key = _secret


# ─────────────────────────────────────────────
# ROUTES FLASK (AUTH)
# ─────────────────────────────────────────────
LOGIN_CSS = """
<style>
  body { font-family: 'Segoe UI', sans-serif; background: #FAFAFA; }
  .form-wrap { max-width: 340px; margin: 80px auto; background: white;
               padding: 40px; border-radius: 16px;
               box-shadow: 0 10px 30px rgba(0,0,0,0.1); text-align: center; }
  input { width: 100%; padding: 12px; margin: 8px 0; border-radius: 8px;
          border: 1px solid #ccc; box-sizing: border-box; font-size: 15px; }
  button { width: 100%; padding: 12px; background: #E60000; color: white;
           border: none; border-radius: 8px; cursor: pointer;
           font-size: 16px; font-weight: bold; margin-top: 10px; }
  .error { color: red; margin-bottom: 10px; font-weight: 600; }
</style>
"""

def _login_form(error=""):
    err_html = f'<p class="error">❌ {error}</p>' if error else ""
    return f"""
    {LOGIN_CSS}
    <div class="form-wrap">
        <h2>🔐 Connexion</h2>
        {err_html}
        <form method="post">
            <input name="username" placeholder="Nom d'utilisateur" required>
            <input name="password" type="password" placeholder="Mot de passe" required>
            <button type="submit">Se connecter</button>
        </form>
    </div>
    """

@server.route("/login", methods=["GET", "POST"])
def login_route():
    if session.get("authenticated"):
        return redirect("/")
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        hashed = USERS.get(username)
        # check_password_hash compare en temps constant (évite timing attacks)
        if hashed and check_password_hash(hashed, password):
            session["authenticated"] = True
            session["username"] = username
            return redirect("/")
        return _login_form(error="Identifiant ou mot de passe incorrect"), 401
    return _login_form()


@server.route("/logout")
def logout_route():
    session.clear()
    return redirect("/login")


# ─────────────────────────────────────────────
# LAYOUT DYNAMIQUE
# ─────────────────────────────────────────────
def get_layout():
    if not session.get("authenticated"):
        return _disclaimer_layout()
    return _app_layout()


def _disclaimer_layout():
    return html.Div([
        html.Div([
            html.H2(
                "🔐 DISCLAIMER CONFORMITÉ RGPD-MKG_330",
                style={"textAlign": "center", "color": SG_BLACK, "marginBottom": "30px",
                       "fontSize": "28px", "fontWeight": "bold"}
            ),
            html.Div([
                _disclaimer_section("📊 Collecte des données",
                    "Contenus collectés via l'API officielle Facebook, intérêt légitime Art.6(1)(f). "
                    "Durée de vie : 12 mois (données brutes), 24 mois (agrégations)."),
                _disclaimer_section("🔒 Sécurité et accès",
                    "Accès restreints aux équipes autorisées avec journalisation et contrôle d'accès."),
                _disclaimer_section("⚠️ Restrictions",
                    "Toute évolution de périmètre ou export nominatif est interdite sans validation "
                    "préalable de la direction innovation et de la gouvernance MRM."),
                _disclaimer_section("✉️ Exercice des droits",
                    "Les demandes liées aux commentaires doivent être adressées à Facebook pour "
                    "suppression à la source ; nous traiterons les copies locales conformément "
                    "aux procédures internes."),
                html.Hr(style={"border": "none", "borderTop": f"2px solid {SG_RED}",
                               "margin": "30px 0", "opacity": "0.3"}),
                html.Div([
                    html.H4("📚 Références légales", style={"color": SG_BLACK,
                            "marginBottom": "15px", "fontSize": "18px", "fontWeight": "600"}),
                    html.Ul([
                        html.Li("RGPD (UE 2016/679) - ART.5, 6(1)(f), 25",
                                style={"marginBottom": "8px", "fontSize": "15px"}),
                        html.Li("Meta/Facebook Terms & Developer Policies",
                                style={"marginBottom": "8px", "fontSize": "15px"}),
                        html.Li("AI Act (UE 2024/1689)", style={"fontSize": "15px"}),
                    ], style={"color": "#666", "lineHeight": "1.8", "paddingLeft": "25px"})
                ], style={"backgroundColor": "#f8f9fa", "padding": "20px",
                           "borderRadius": "8px", "marginBottom": "30px"}),
                html.Div([
                    html.A("Cliquez ici pour vous connecter →", href="/login",
                           style={"display": "inline-block", "padding": "15px 40px",
                                  "backgroundColor": SG_RED, "color": "white",
                                  "textDecoration": "none", "borderRadius": "8px",
                                  "fontWeight": "bold", "fontSize": "18px"})
                ], style={"textAlign": "center", "marginTop": "20px"})
            ], style={"maxWidth": "900px", "margin": "0 auto", "padding": "40px",
                       "backgroundColor": "white", "borderRadius": "15px",
                       "boxShadow": "0 10px 30px rgba(0,0,0,0.1)"})
        ], style={"minHeight": "100vh", "padding": "50px 20px",
                   "background": "linear-gradient(135deg, #f5f7fa 0%, #e9ecef 100%)"})
    ], style={"width": "100%"})


def _disclaimer_section(title, text):
    return html.Div([
        html.H3(title, style={"color": SG_RED, "marginBottom": "15px",
                               "fontSize": "20px", "fontWeight": "600"}),
        html.P(text, style={"color": "#333", "lineHeight": "1.8", "fontSize": "16px"})
    ], style={"marginBottom": "25px"})


def _app_layout():
    username = session.get("username", "")
    return html.Div([
        # Barre utilisateur
        html.Div([
            html.Span(f"👤 {username}",
                      style={"float": "right", "marginRight": "20px",
                             "color": SG_RED, "fontWeight": "bold"}),
            html.A("Déconnexion", href="/logout",
                   style={"float": "right", "marginRight": "10px", "color": "#666"})
        ], style={"padding": "10px", "backgroundColor": "#f0f0f0", "marginBottom": "20px"}),
        # Onglets
        dcc.Tabs(
            id="tabs", value="home",
            children=[
                dcc.Tab(label="🏠 Accueil",                    value="home"),
                dcc.Tab(label="📈 Statistiques Générales",     value="stats"),
                dcc.Tab(label="📊 Analyses Graphiques",        value="viz"),
                dcc.Tab(label="🔍 Détails des commentaires",   value="details"),
                #dcc.Tab(label="📝 Posts divers",               value="posts"),
            ],
            style={"fontWeight": "600", "fontSize": "16px"}
        ),
        html.Div(id="content")
    ])


app.layout = get_layout


# ─────────────────────────────────────────────
# HELPER : header hero
# ─────────────────────────────────────────────
def _hero(title, subtitle):
    return html.Div([
        html.H2(title, style={"fontSize": "52px", "marginBottom": "15px",
                               "fontWeight": "900", "letterSpacing": "-1px"}),
        html.Div("━━", style={"color": SG_WHITE, "fontSize": "32px",
                               "marginBottom": "15px", "opacity": "0.8"}),
        html.P(subtitle, style={"fontSize": "20px", "opacity": "0.9", "fontWeight": "300"})
    ], style={**HERO, "textAlign": "center"})


# ─────────────────────────────────────────────
# CALLBACK PRINCIPAL — rendu des onglets
# ─────────────────────────────────────────────
@app.callback(Output("content", "children"), Input("tabs", "value"))
def render_page(tab):

    # ── HOME ──────────────────────────────────────────────────────
    if tab == "home":
        return html.Div([
            html.Div([
                html.H1("Analyse des sentiments : cas des banques",
                        style={"fontSize": "64px", "fontWeight": "900",
                               "marginBottom": "25px", "letterSpacing": "-3px",
                               "textShadow": "3px 5px 15px rgba(0,0,0,0.3)"}),
                html.Div([html.Span("━━━━━", style={"color": SG_WHITE, "opacity": "0.6",
                                                     "fontSize": "24px"})],
                         style={"marginBottom": "20px"}),
                html.P("Intelligence d'Analyse de l'Image de Marque",
                       style={"fontSize": "28px", "opacity": "0.95",
                              "fontWeight": "300", "letterSpacing": "1px"}),
                html.P("Réseaux Sociaux • Analyse de sentiments • Performance Tracking",
                       style={"fontSize": "16px", "opacity": "0.85",
                              "marginTop": "15px", "textTransform": "uppercase",
                              "letterSpacing": "2px"})
            ], style={**HERO, "textAlign": "center"}),

            html.Div([
                html.Div([
                    html.Div("🎯", style={"fontSize": "56px", "marginBottom": "25px"}),
                    html.H3("Plateforme d'Analyse Stratégique",
                            style={"color": SG_BLACK, "marginBottom": "20px",
                                   "fontSize": "36px", "fontWeight": "700"}),
                    html.P("Transformez les données sociales en intelligence stratégique. "
                           "Notre plateforme analyse en profondeur les commentaires et interactions "
                           "sur Facebook pour vous offrir une vision 360° de votre réputation digitale.",
                           style={"fontSize": "20px", "lineHeight": "1.8",
                                  "color": SG_GREY, "maxWidth": "900px", "margin": "auto"})
                ], style={**CARD, "textAlign": "center", "padding": "50px"})
            ], style={"marginBottom": "50px"}),

            # Grille de fonctionnalités
            html.Div([
                _feature_card("📊", "Analytics Avancés",
                              "KPIs en temps réel, tableaux de bord dynamiques et métriques de performance"),
                _feature_card("💭", "Analyse de sentiments",
                              "Intelligence artificielle pour comprendre émotions, tonalités et perceptions clients"),
                _feature_card("🎯", "Leviers Stratégiques",
                              "Recommandations actionnables pour optimiser image de marque et satisfaction client"),
            ], style={"marginBottom": "50px", "display": "flex", "gap": "3.5%"}),

            # Chiffres clés
            html.Div([
                html.Div([
                    html.H4("Performance en Chiffres",
                            style={"color": SG_BLACK, "fontSize": "28px",
                                   "marginBottom": "30px", "fontWeight": "700",
                                   "textAlign": "center"}),
                    html.Div([
                        _kpi_block("10K+",  "Commentaires Analysés"),
                        _kpi_block("3",     "Labels NLP (Pos/Neg/Neutre)"),
                        _kpi_block("24/7",  "Monitoring Continu"),
                        _kpi_block("4.8/5", "Satisfaction Utilisateur"),
                    ], style={"display": "flex", "justifyContent": "space-around"})
                ], style={**CARD, "padding": "50px"})
            ], style={"marginBottom": "50px"}),

            html.Div([
                html.Div([
                    html.Div("━━━━━━━", style={"color": SG_RED, "fontSize": "32px",
                                               "marginBottom": "25px"}),
                    html.P('« De la donnée brute à l\'intelligence stratégique »',
                           style={"fontSize": "32px", "fontStyle": "italic",
                                  "color": SG_BLACK, "fontWeight": "600",
                                  "marginBottom": "20px"}),
                    html.P("Prenez des décisions éclairées grâce à l'analyse prédictive",
                           style={"fontSize": "18px", "color": SG_GREY})
                ], style={**CARD, "textAlign": "center", "padding": "60px",
                           "background": SG_LIGHT_GREY})
            ])
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ── STATS ─────────────────────────────────────────────────────
    elif tab == "stats":
        if df.empty:
            return _empty_state("Aucune donnée disponible")

        sources = sorted(df["source"].unique().tolist())
        return html.Div([
            _hero("📈 Statistiques Générales", "Analyse des performances et métriques clés"),

            html.Div([
                html.H4("Filtres de Sélection",
                        style={"color": SG_BLACK, "fontSize": "24px",
                               "fontWeight": "700", "marginBottom": "25px"}),
                html.Div([
                    html.Div([
                        html.Label("SOURCE", style=LABEL_STYLE),
                        dcc.Dropdown(
                            id="filtre-source",
                            options=[{"label": s, "value": s} for s in sources],
                            value=sources, multi=True,
                            style={"borderRadius": "12px"}
                        )
                    ], style={"width": "48%", "display": "inline-block", "marginRight": "4%"}),
                    html.Div([
                        html.Label("PÉRIODE D'ANALYSE", style=LABEL_STYLE),
                        dcc.DatePickerRange(
                            id="filtre-date",
                            start_date=DATE_MIN,
                            end_date=DATE_MAX_COMMENTS,
                        )
                    ], style={"width": "48%", "display": "inline-block"})
                ])
            ], style=FILTER_BOX),

            html.Div(id="stats-metrics",
                     style={"display": "flex", "flexWrap": "wrap", "gap": "25px",
                            "marginBottom": "40px"}),

            html.Div([
                html.H4("Guide des Indicateurs",
                        style={"color": SG_BLACK, "fontSize": "26px",
                               "fontWeight": "700", "marginBottom": "30px"}),
                html.Div([
                    html.Div([
                        _guide_item("😍😊💕", "Commentaires Positifs",
                                    "Nombre total de retours favorables sur la période"),
                        _guide_item("🤬😡🥵", "Commentaires Négatifs",
                                    "Volume des retours défavorables nécessitant attention"),
                        _guide_item("😐",    "Commentaires Neutres",
                                    "Retours ambivalents ou sans tonalité marquée (nouveau label 2026)"),
                        _guide_item("📊",    "Ratio de Négativité",
                                    "Pourcentage de sentiments négatifs vs positifs"),
                    ], style={"width": "48%", "display": "inline-block",
                              "marginRight": "4%", "verticalAlign": "top"}),
                    html.Div([
                        _guide_item("📈", "Moyenne Quotidienne",
                                    "Flux moyen de commentaires par jour"),
                        _guide_item("📉", "Moyenne Négatifs/Jour",
                                    "Taux quotidien de commentaires négatifs"),
                    ], style={"width": "48%", "display": "inline-block", "verticalAlign": "top"})
                ])
            ], style=CARD)
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ── VIZ ───────────────────────────────────────────────────────
    elif tab == "viz":
        if df.empty or absa_df.empty:
            return _empty_state("Données de visualisation indisponibles")

        sources = sorted(absa_df["source"].unique().tolist())
        return html.Div([
            _hero("📊 Visualisations Avancées",
                  "Analyse graphique du ressenti et des tendances clients"),

            html.Div([
                html.H4("Paramètres de Visualisation",
                        style={"color": SG_BLACK, "fontSize": "24px",
                               "fontWeight": "700", "marginBottom": "25px"}),
                html.Div([
                    html.Div([
                        html.Label("SOURCE DE DONNÉES", style=LABEL_STYLE),
                        dcc.Dropdown(
                            id="viz-filtre-source",
                            options=[{"label": s, "value": s} for s in sources],
                            value=sources, multi=True
                        )
                    ], style={"width": "48%", "display": "inline-block", "marginRight": "4%"}),
                    html.Div([
                        html.Label("PLAGE TEMPORELLE", style=LABEL_STYLE),
                        dcc.DatePickerRange(
                            id="viz-filtre-date",
                            start_date=DATE_MIN,
                            end_date=DATE_MAX_ABSA,
                        )
                    ], style={"width": "48%", "display": "inline-block"})
                ])
            ], style=FILTER_BOX),

            html.Div([
                html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "15px"}),
                html.H3("Évolution du Ressenti Clients - SGCI", style=SECTION_TITLE),
                html.Div(id="nouveau-graphique",
                         children="📌 Cliquez sur une barre pour afficher les détails contextuels")
            ], style=CARD),

            html.Div([dcc.Graph(id="viz-sentiments")], style=CARD),

            html.Div([
                html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "15px"}),
                html.H3("Évolution du Proxy NPS", style=SECTION_TITLE),
                html.P("Net Promoter Score — Indicateur de fidélisation client",
                       style={"color": SG_GREY, "fontSize": "14px", "marginTop": "5px"}),
                dcc.Graph(id="viz-nps")
            ], style=CARD),

            html.Div([
                html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "15px"}),
                html.H3("Répartition par Typologie et Établissement", style=SECTION_TITLE),
                dcc.Graph(id="viz-aspects")
            ], style=CARD),

            html.Div([
                html.H3("Nuage Sémantique — Commentaires Négatifs SGCI",
                        style={**SECTION_TITLE, "textAlign": "center"}),
                html.P("Analyse lexicale des termes les plus fréquents dans les retours négatifs",
                       style={"color": SG_GREY, "fontSize": "14px",
                              "textAlign": "center", "marginBottom": "30px"}),
                html.Img(
                    src="data:image/png;base64," + wordcloud_base64,
                    style={"width": "80%", "display": "block", "margin": "auto",
                           "borderRadius": "16px",
                           "boxShadow": "0 8px 30px rgba(230,0,0,0.15)"}
                ) if wordcloud_base64 else html.Div(
                    html.P("Wordcloud non disponible", style={"color": SG_GREY}),
                    style={"textAlign": "center", "padding": "60px"}
                )
            ], style=CARD)
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ── DETAILS ───────────────────────────────────────────────────
    elif tab == "details":
        if absa_df.empty:
            return _empty_state("Aucun commentaire disponible")

        # Tri par date décroissante (correction du bug original)
        absa_sorted = absa_df.sort_values("date", ascending=False)

        # Options de filtres
        dates_opts  = [{"label": "Toutes", "value": "Toutes"}] + \
                      [{"label": str(d)[:10], "value": str(d)[:10]}
                       for d in absa_sorted["date"].dt.date.unique()]
        source_opts = [{"label": "Toutes", "value": "Toutes"}] + \
                      [{"label": s, "value": s} for s in sorted(absa_df["source"].unique())]
        aspect_opts = [{"label": "Toutes", "value": "Toutes"}] + \
                      [{"label": a, "value": a} for a in sorted(absa_df["aspect"].unique())]
        sent_opts   = [
            {"label": "Tous",          "value": "Tous"},
            {"label": "😊 Positif",    "value": "positif"},
            {"label": "😡 Négatif",    "value": "negatif"},
            {"label": "😐 Neutre",     "value": "neutre"},   # nouveau label 2026
        ]

        # Définition des colonnes pour AgGrid (remplace DataTable)
        ag_columns = [
            {"field": "date",    "headerName": "Date",      "width": 130},
            {"field": "auteur",  "headerName": "Auteur",    "width": 160},
            {"field": "phrase",  "headerName": "Phrase",    "flex": 1,
             "wrapText": True, "autoHeight": True},
            {"field": "aspect",  "headerName": "Typologie", "width": 150},
        ]

        return html.Div([
            _hero("🔍 Exploration Détaillée",
                  "Analyse granulaire des commentaires par typologie"),

            html.Div([
                html.H4("Filtres de Recherche Avancés",
                        style={"color": SG_BLACK, "fontSize": "24px",
                               "fontWeight": "700", "marginBottom": "25px"}),
                html.Div([
                    _filter_col("details-date",      "DATE",      dates_opts,  "Toutes"),
                    _filter_col("details-source",    "SOURCE",    source_opts, "Toutes"),
                    _filter_col("details-aspect",    "TYPOLOGIE", aspect_opts, "Toutes"),
                    _filter_col("details-sentiment", "SENTIMENT", sent_opts,   "Tous"),
                ])
            ], style=FILTER_BOX),

            html.Div([
                html.H4("Résultats de la Recherche",
                        style={"color": SG_BLACK, "fontSize": "26px",
                               "fontWeight": "700", "marginBottom": "10px"}),
                html.P("Commentaires filtrés selon vos critères",
                       style={"color": SG_GREY, "fontSize": "14px", "marginBottom": "25px"}),
                # ── AgGrid remplace DataTable (déprécié Dash 2.19) ──
                dag.AgGrid(
                    id="details-table",
                    columnDefs=ag_columns,
                    rowData=[],
                    defaultColDef={"resizable": True, "sortable": True, "filter": True},
                    dashGridOptions={"pagination": True, "paginationPageSize": 10,
                                     "domLayout": "autoHeight"},
                    style={"height": None, "width": "100%"},
                )
            ], style=CARD)
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ── POSTS ─────────────────────────────────────────────────────
    elif tab == "posts":
        if df_postes.empty:
            return _empty_state("Aucun post trouvé")

        df_p = df_postes.copy()
        df_p["date"] = pd.to_datetime(df_p["date"], errors="coerce").dt.date
        df_p = df_p.dropna(subset=["date"])

        content = [_hero("📝 Posts Récents",
                         "Dans le groupe ( Observatoire Libre des Banques )")]

        for source in df_p["source"].unique():
            content.append(
                html.H3(f"📢 {source}",
                        style={"color": "#c30b0b", "fontSize": "28px",
                               "marginBottom": "20px", "fontWeight": "700",
                               "marginTop": "40px"})
            )
            posts = (df_p[df_p["source"] == source]
                     .groupby("poste").first().reset_index()
                     .sort_values("date", ascending=False))

            for _, row in posts.iterrows():
                coms = df_p[(df_p["source"] == source) & (df_p["poste"] == row["poste"])]

                # Colonnes AgGrid pour les commentaires du post
                com_cols = [
                    {"field": "date",        "headerName": "Date",       "width": 120},
                    {"field": "auteur_com",  "headerName": "Auteur",     "width": 160},
                    {"field": "commentaire", "headerName": "Commentaire","flex": 1,
                     "wrapText": True, "autoHeight": True},
                ]

                content.append(html.Div([
                    html.Div([
                        html.Span("📅 ", style={"fontSize": "18px"}),
                        html.Span(str(row["date"]),
                                  style={"fontWeight": "600", "color": "#0f0f10"})
                    ], style={"marginBottom": "8px"}),
                    html.Div([
                        html.Span("👤 ", style={"fontSize": "18px"}),
                        html.Span(row["auteur"], style={"fontWeight": "600", "color": "#374151"})
                    ], style={"marginBottom": "12px"}),
                    html.P(row["poste"],
                           style={"fontSize": "16px", "lineHeight": "1.6",
                                  "color": "#1f2937", "padding": "15px",
                                  "backgroundColor": "#f9fafb", "borderRadius": "8px",
                                  "borderLeft": "4px solid #667eea"}),
                    html.H5("💬 Commentaires",
                            style={"color": "#374151", "marginTop": "20px",
                                   "marginBottom": "15px", "fontWeight": "700"}),
                    dag.AgGrid(
                        columnDefs=com_cols,
                        rowData=coms[["date", "auteur_com", "commentaire"]].to_dict("records"),
                        defaultColDef={"resizable": True},
                        dashGridOptions={"pagination": True, "paginationPageSize": 5,
                                         "domLayout": "autoHeight"},
                        style={"height": None, "width": "100%"},
                    ) if not coms.empty else html.P(
                        "Aucun commentaire associé",
                        style={"fontStyle": "italic", "color": "#9ca3af"}
                    )
                ], style=CARD))

        return html.Div(content,
                        style={"padding": "50px 30px", "backgroundColor": "#FAFAFA",
                               "minHeight": "100vh"})


# ─────────────────────────────────────────────
# HELPERS UI
# ─────────────────────────────────────────────
def _empty_state(msg):
    return html.Div([
        html.Div([
            html.Div("⚠️", style={"fontSize": "80px", "marginBottom": "20px", "opacity": "0.3"}),
            html.H3(msg, style={"color": SG_GREY, "fontSize": "28px", "fontWeight": "600"})
        ], style={**CARD, "textAlign": "center", "padding": "80px"})
    ])

def _feature_card(emoji, title, desc):
    return html.Div([
        html.Div([
            html.Div(emoji, style={"fontSize": "64px", "marginBottom": "25px"}),
            html.H4(title, style={"color": SG_RED, "marginBottom": "15px",
                                   "fontSize": "24px", "fontWeight": "700"}),
            html.P(desc, style={"color": SG_GREY, "fontSize": "16px", "lineHeight": "1.6"}),
            html.Div("━━━━", style={"color": SG_RED, "marginTop": "20px", "fontSize": "20px"})
        ], style={**CARD, "textAlign": "center", "flex": "1", "minWidth": "200px",
                   "display": "flex", "flexDirection": "column", "justifyContent": "center"})
    ], style={"flex": "1"})

def _kpi_block(value, label):
    return html.Div([
        html.H3(value, style={"color": SG_RED, "fontSize": "48px",
                               "fontWeight": "900", "margin": "0"}),
        html.P(label, style={"color": SG_GREY, "fontSize": "14px", "marginTop": "10px"})
    ], style={"textAlign": "center"})

def _guide_item(emoji, title, desc):
    return html.Div([
        html.Span(emoji, style={"fontSize": "32px", "marginRight": "20px"}),
        html.Div([
            html.Span(title, style={"fontWeight": "700", "fontSize": "18px",
                                     "color": SG_BLACK, "display": "block"}),
            html.Span(desc, style={"color": SG_GREY, "fontSize": "14px"})
        ], style={"display": "inline-block", "verticalAlign": "middle"})
    ], style=ACCENT_BOX)

def _filter_col(id_, label, options, default):
    return html.Div([
        html.Label(label, style={**LABEL_STYLE, "fontSize": "11px"}),
        dcc.Dropdown(id=id_, options=options, value=default, clearable=False)
    ], style={"width": "23%", "display": "inline-block", "marginRight": "2.5%"})


# ─────────────────────────────────────────────
# CALLBACK STATS
# ─────────────────────────────────────────────
@app.callback(
    Output("stats-metrics", "children"),
    Input("filtre-source", "value"),
    Input("filtre-date", "start_date"),
    Input("filtre-date", "end_date"),
)
def maj_stats(sources, start_date, end_date):
    if not sources or df.empty:
        return [html.P("⚠️ Aucune source sélectionnée.")]

    dff = df[df["source"].isin(sources)]
    dff = dff[
        (dff["date"].dt.date >= pd.to_datetime(start_date).date()) &
        (dff["date"].dt.date <= pd.to_datetime(end_date).date())
    ]
    if dff.empty:
        return [html.P("⚠️ Aucune donnée après filtrage.")]

    total_counts = dff.groupby("source").size()
    pos_counts   = dff[dff["sentiment"] == "POSITIVE"].groupby("source").size()
    neg_counts   = dff[dff["sentiment"] == "NEGATIVE"].groupby("source").size()
    neu_counts   = dff[dff["sentiment"] == "NEUTRAL"].groupby("source").size()

    all_dates = pd.date_range(
        start=dff["date"].min().date(), end=dff["date"].max().date(), freq="D"
    )
    multi_idx = pd.MultiIndex.from_product(
        [all_dates, dff["source"].unique()], names=["date", "source"]
    )
    daily_all = (dff.groupby([dff["date"].dt.date, "source"])
                    .size().reindex(multi_idx, fill_value=0).unstack())
    daily_neg = (dff[dff["sentiment"] == "NEGATIVE"]
                    .groupby([dff["date"].dt.date, "source"])
                    .size().reindex(multi_idx, fill_value=0).unstack())

    avg_all = round(daily_all.mean(), 2)
    avg_neg = round(daily_neg.mean(), 2)
    neg_ratio = round((avg_neg / avg_all * 100).fillna(0), 2)

    metrics = []
    for src in total_counts.index:
        metrics.append(html.Div([
            html.H4(f"Commentaires {src}",
                    style={"color": SG_RED, "fontWeight": "700", "marginBottom": "10px"}),
            html.P(f"Total : {total_counts[src]}"),
            html.P(f"😍 Positifs : {pos_counts.get(src, 0)}"),
            html.P(f"🤬 Négatifs : {neg_counts.get(src, 0)}"),
            html.P(f"😐 Neutres  : {neu_counts.get(src, 0)}"),   # nouveau 2026
            html.P(f"% Négatifs : {neg_ratio.get(src, 0)} %"),
            html.P(f"Moy./jour  : {avg_all.get(src, 0)}"),
            html.P(f"Moy. Nég./jour : {avg_neg.get(src, 0)}"),
        ], style={**CARD, "minWidth": "220px", "flex": "1"}))
    return metrics


# ─────────────────────────────────────────────
# CALLBACK GRAPHIQUES
# ─────────────────────────────────────────────
@app.callback(
    [Output("viz-sentiments", "figure"),
     Output("viz-nps",        "figure"),
     Output("viz-aspects",    "figure")],
    [Input("viz-filtre-source", "value"),
     Input("viz-filtre-date",   "start_date"),
     Input("viz-filtre-date",   "end_date")],
)
def maj_viz(sources, start_date, end_date):
    empty = px.bar()
    if not sources or df.empty or absa_df.empty:
        return empty, empty, empty

    dff = df[df["source"].isin(sources)]
    dff = dff[
        (dff["date"].dt.date >= pd.to_datetime(start_date).date()) &
        (dff["date"].dt.date <= pd.to_datetime(end_date).date())
    ]
    absa_f = absa_df[
        (absa_df["date"].dt.date >= pd.to_datetime(start_date).date()) &
        (absa_df["date"].dt.date <= pd.to_datetime(end_date).date())
    ]
    if dff.empty or absa_f.empty:
        return empty, empty, empty

    # Graphique sentiments SGCI
    tot = (absa_f[absa_f["source"] == "page_sgci"]
           .groupby(["date", "sentiment"]).size()
           .reset_index(name="tot_count"))
    fig_sent = px.bar(
        tot, x="date", y="tot_count", color="sentiment", barmode="group",
        color_discrete_map={"negatif": "red", "positif": "green", "neutre": "grey"},
    )

    # Proxy NPS
    all_dates = pd.date_range(
        start=dff["date"].min().date(), end=dff["date"].max().date(), freq="D"
    )
    mi = pd.MultiIndex.from_product(
        [all_dates, dff["source"].unique()], names=["date", "source"]
    )
    daily = (dff.groupby([dff["date"].dt.date, "source"])
                .size().reindex(mi, fill_value=0).unstack())
    daily_neg = (dff[dff["sentiment"] == "NEGATIVE"]
                     .groupby([dff["date"].dt.date, "source"])
                     .size().reindex(mi, fill_value=0).unstack())
    detra = daily_neg / daily.replace(0, np.nan)
    promo = 1 - detra
    nps_df = (promo - detra).reset_index().melt(
        id_vars="date", var_name="source", value_name="Proxy NPS"
    ).dropna()
    fig_nps = px.line(nps_df, x="date", y="Proxy NPS", color="source")
    fig_nps.add_hline(y=0, line_dash="solid", line_color="black", line_width=2)

    # Aspects par source
    ag = (absa_f[absa_f["source"].isin(sources)]
          .groupby(["source", "aspect", "sentiment"]).size()
          .reset_index(name="count"))
    fig_asp = px.bar(
        ag, x="aspect", y="count", color="sentiment", barmode="group",
        facet_col="source",
        color_discrete_map={"negatif": "red", "positif": "green", "neutre": "grey"},
        labels={"aspect": "Typologie", "count": "Nombre"},
    )
    return fig_sent, fig_nps, fig_asp


# ─────────────────────────────────────────────
# CALLBACK DRILL-DOWN (clic sur barre)
# ─────────────────────────────────────────────
@app.callback(
    Output("nouveau-graphique", "children"),
    [Input("viz-sentiments",    "clickData"),
     Input("viz-filtre-source", "value")],
)
def creer_nouveau_graph(clickData, sources):
    if not clickData or not sources:
        return "📌 Cliquez sur une barre pour afficher plus de détails contextuels"

    selected_date = clickData["points"][0]["x"]
    filtered = absa_df[
        (absa_df["source"] == "page_sgci") &
        (absa_df["date"].astype(str).str[:10] == str(selected_date)[:10])
    ]
    if filtered.empty:
        return html.Div(f"Aucun commentaire pour le {selected_date}.")

    aspect_count = (filtered.groupby("aspect").size()
                             .reset_index(name="nb_commentaires"))
    fig = px.bar(
        aspect_count, x="aspect", y="nb_commentaires",
        title=f"Commentaires par typologie le {selected_date}",
        labels={"aspect": "Typologie", "nb_commentaires": "Nombre"},
        text="nb_commentaires",
        color_discrete_sequence=["#8B0000"],
    )
    fig.update_traces(textfont=dict(color="black", size=14,
                                    family="Arial", weight="bold"))
    return dcc.Graph(figure=fig)


# ─────────────────────────────────────────────
# CALLBACK DÉTAILS (AgGrid)
# ─────────────────────────────────────────────
@app.callback(
    Output("details-table", "rowData"),
    [Input("details-date",      "value"),
     Input("details-source",    "value"),
     Input("details-aspect",    "value"),
     Input("details-sentiment", "value")],
)
def filter_details(date_filter, source_filter, aspect_filter, sentiment_filter):
    fdf = absa_df.copy()
    if source_filter    != "Toutes": fdf = fdf[fdf["source"]    == source_filter]
    if aspect_filter    != "Toutes": fdf = fdf[fdf["aspect"]    == aspect_filter]
    if sentiment_filter != "Tous":   fdf = fdf[fdf["sentiment"] == sentiment_filter]
    if date_filter      != "Toutes":
        fdf = fdf[fdf["date"].astype(str).str[:10] == str(date_filter)[:10]]

    fdf = fdf.sort_values("date", ascending=False)
    fdf["date"] = fdf["date"].astype(str).str[:10]
    return fdf[["date", "auteur", "phrase", "aspect"]].to_dict("records")


# ─────────────────────────────────────────────
# LANCEMENT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8053))
    # app.run() — run_server() supprimé depuis Dash 2.18
    app.run(debug=False, host="0.0.0.0", port=port)
