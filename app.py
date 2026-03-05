import dash
from dash import dcc, html, Input, Output, dash_table
import pandas as pd
import plotly.express as px
import numpy as np
import json
from PIL import Image
import base64
import datetime as dt
import subprocess
import os
import io
from flask import session, redirect, request

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))


USERS = {
    "admin": "motdepasse123",
    "analyste": "analyse2025"
}


df_postes = pd.read_csv("postes.csv")


def load_data():
    try:
        df = pd.read_csv("resultats_sentiments.csv")
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df.dropna(subset=['date'], inplace=True)
    except:  # noqa: E722
        df = pd.DataFrame()
    try:
        with open("kpis.json") as f:
            kpis = json.load(f)
    except:  # noqa: E722
        kpis = {}
    try:
        absa_df = pd.read_csv( "absa_df.csv")
    except:  # noqa: E722
        absa_df = pd.DataFrame()
    try:
        df_postes = pd.read_csv("postes.csv")
    except:  # noqa: E722
        df_postes = pd.DataFrame()
    try:
        wordcloud_img = Image.open("wordcloud.png")
        # Encodage en base64 pour affichage dans Dash
        buf = io.BytesIO()
        wordcloud_img.save(buf, format="PNG")
        wordcloud_base64 = base64.b64encode(buf.getvalue()).decode()
    except:  # noqa: E722
        wordcloud_base64 = None
    return df, kpis, absa_df, df_postes, wordcloud_base64


df, kpis, absa_df, df_postes, wordcloud_base64 = load_data()
if not df.empty:
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
if not absa_df.empty:
    absa_df["date"] = pd.to_datetime(absa_df["date"], errors="coerce")


def query_llama(prompt, model="llama3"):
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=30
        )
        output = result.stdout.decode("utf-8").strip()
        return output
    except Exception as e:
        return f"⚠️ Erreur LLaMA : {e}"


app = dash.Dash(__name__, suppress_callback_exceptions=True)
server = app.server
server.secret_key = os.environ.get("SECRET_KEY", "super-secret-key-for-dev-only")

# === Route login ===
@server.route("/login", methods=["GET", "POST"])
def login_route():
    if session.get("authenticated"):
        return redirect("/")
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USERS and USERS[username] == password:
            session["authenticated"] = True
            session["username"] = username
            return redirect("/")
        else:
            return '''
            <h3 style="color:red;text-align:center;margin-top:50px;">❌ Identifiant ou mot de passe incorrect</h3>
            <form method="post" style="max-width:300px;margin:auto;text-align:center;">
                <input name="username" placeholder="Nom d'utilisateur" required style="width:100%;padding:10px;margin:10px 0;border-radius:6px;border:1px solid #ccc;"><br>
                <input name="password" type="password" placeholder="Mot de passe" required style="width:100%;padding:10px;margin:10px 0;border-radius:6px;border:1px solid #ccc;"><br>
                <button type="submit" style="width:100%;padding:10px;background:#E60000;color:white;border:none;border-radius:6px;cursor:pointer;">Se connecter</button>
            </form>
            <style>body{font-family:sans-serif;background:#f9f9f9;}</style>
            '''
    return '''
    <form method="post" style="max-width:300px;margin:auto;text-align:center;margin-top:100px;">
        <h2>🔐 Connexion</h2>
        <input name="username" placeholder="Nom d'utilisateur" required style="width:100%;padding:10px;margin:10px 0;border-radius:6px;border:1px solid #ccc;"><br>
        <input name="password" type="password" placeholder="Mot de passe" required style="width:100%;padding:10px;margin:10px 0;border-radius:6px;border:1px solid #ccc;"><br>
        <button type="submit" style="width:100%;padding:10px;background:#E60000;color:white;border:none;border-radius:6px;cursor:pointer;">Se connecter</button>
    </form>
    <style>body{font-family:'Segoe UI',sans-serif;background:#FAFAFA;}</style>
    '''


@server.route("/logout")
def logout_route():
    session.pop("authenticated", None)
    session.pop("username", None)
    return redirect("/login")

# Menu principal
# app.layout = html.Div([
#     dcc.Tabs(
#         id="tabs",
#         value="home",
#         children=[
#             dcc.Tab(label="🏠 Accueil", value="home"),
#             dcc.Tab(label="📈 Statistiques Générales", value="stats"),
#             dcc.Tab(label="📊 Analyses Graphiques", value="viz"),

#             # 🔥 Onglet stylé avec badge rouge via style et pseudo-élément CSS
#             dcc.Tab(
#                 label="🔍 Détails des commentaires",
#                 value="details",
#                 className="tab-alert"
#             ),

#             dcc.Tab(label="📝 Posts divers", value="posts"),
#         ],
#         style={"fontWeight": "600", "fontSize": "16px"}
#     ),
#     html.Div(id="content")
# ])


def get_layout():
    # CHARTRE SG
    SG_RED = "#E60000"
    SG_BLACK = "#000000"

    if not session.get("authenticated"):
        return html.Div([html.Div([html.H2(
            "🔐 DISCLAIMER CONFORMITÉ RGPD-MKG_330",
            style={
                "textAlign": "center",
                "color": SG_BLACK,
                "marginBottom": "30px",
                "fontSize": "28px",
                "fontWeight": "bold"
            }
        ),
        
        html.Div([
            # Section 1: Collecte des données
            html.Div([
                html.H3(
                    "📊 Collecte des données",
                    style={
                        "color": SG_RED,
                        "marginBottom": "15px",
                        "fontSize": "20px",
                        "fontWeight": "600"
                    }
                ),
                html.P(
                    "Cette solution digitale repose uniquement sur des contenus collectés via l'API officielle de Facebook avec pour intérêt légitime appuyé par l'Art.6(1)(f).",
                    style={
                        "color": "#333",
                        "lineHeight": "1.8",
                        "fontSize": "16px",
                        "marginBottom": "10px"
                    }
                ),
                html.P(
                    "Les données brutes ont une durée de vie de 12 mois maximum et les agrégations iront jusqu'à 24 mois.",
                    style={
                        "color": "#555",
                        "lineHeight": "1.8",
                        "fontSize": "15px",
                        "fontStyle": "italic"
                    }
                )
            ], style={"marginBottom": "25px"}),
            
            # Section 2: Sécurité et accès
            html.Div([
                html.H3(
                    "🔒 Sécurité et accès",
                    style={
                        "color": SG_RED,
                        "marginBottom": "15px",
                        "fontSize": "20px",
                        "fontWeight": "600"
                    }
                ),
                html.P(
                    "Les accès sont restreints aux équipes autorisées, avec journalisation et contrôle d'accès.",
                    style={
                        "color": "#333",
                        "lineHeight": "1.8",
                        "fontSize": "16px"
                    }
                )
            ], style={"marginBottom": "25px"}),
            
            # Section 3: Restrictions
            html.Div([
                html.H3(
                    "⚠️ Restrictions",
                    style={
                        "color": SG_RED,
                        "marginBottom": "15px",
                        "fontSize": "20px",
                        "fontWeight": "600"
                    }
                ),
                html.P(
                    "Toute évolution de périmètre ou export nominatif est interdite sans validation préalable de la direction innovation et de la gouvernance MRM.",
                    style={
                        "color": "#333",
                        "lineHeight": "1.8",
                        "fontSize": "16px"
                    }
                )
            ], style={"marginBottom": "25px"}),
            
            # Section 4: Exercice des droits
            html.Div([
                html.H3(
                    "✉️ Exercice des droits",
                    style={
                        "color": SG_RED,
                        "marginBottom": "15px",
                        "fontSize": "20px",
                        "fontWeight": "600"
                    }
                ),
                html.P(
                    "Pour l'exercice des droits, les demandes liées aux commentaires doivent être adressées à Facebook pour suppression à la source ; nous traiterons les copies locales conformément aux procédures internes.",
                    style={
                        "color": "#333",
                        "lineHeight": "1.8",
                        "fontSize": "16px"
                    }
                )
            ], style={"marginBottom": "30px"}),
            
            # Séparateur
            html.Hr(style={
                "border": "none",
                "borderTop": f"2px solid {SG_RED}",
                "margin": "30px 0",
                "opacity": "0.3"
            }),
            
            # Références légales
            html.Div([
                html.H4(
                    "📚 Références légales",
                    style={
                        "color": SG_BLACK,
                        "marginBottom": "15px",
                        "fontSize": "18px",
                        "fontWeight": "600"
                    }
                ),
                html.Ul([
                    html.Li("RGPD (UE 2016/679) - ART.5, 6(1)(f), 25", 
                           style={"marginBottom": "8px", "fontSize": "15px"}),
                    html.Li("Meta/Facebook Terms & Developer Policies", 
                           style={"marginBottom": "8px", "fontSize": "15px"}),
                    html.Li("AI Act (UE 2024/1689)", 
                           style={"fontSize": "15px"})
                ], style={
                    "color": "#666",
                    "lineHeight": "1.8",
                    "paddingLeft": "25px"
                })
            ], style={
                "backgroundColor": "#f8f9fa",
                "padding": "20px",
                "borderRadius": "8px",
                "marginBottom": "30px"
            }),
            
            # Bouton de connexion
            html.Div([
                html.A(
                    "Cliquez ici pour vous connecter →",
                    href="/login",
                    style={
                        "display": "inline-block",
                        "padding": "15px 40px",
                        "backgroundColor": SG_RED,
                        "color": "white",
                        "textDecoration": "none",
                        "borderRadius": "8px",
                        "fontWeight": "bold",
                        "fontSize": "18px",
                        "boxShadow": "0 4px 6px rgba(0,0,0,0.1)",
                        "transition": "all 0.3s ease"
                    }
                )
            ], style={
                "textAlign": "center",
                "marginTop": "20px"
            })
            
        ], style={
            "maxWidth": "900px",
            "margin": "0 auto",
            "padding": "40px",
            "backgroundColor": "white",
            "borderRadius": "15px",
            "boxShadow": "0 10px 30px rgba(0,0,0,0.1)"
        })
        
    ], style={
        "minHeight": "100vh",
        "padding": "50px 20px",
        "background": "linear-gradient(135deg, #f5f7fa 0%, #e9ecef 100%)"
    })
], style={"width": "100%"})

    # Si authentifié → layout complet
    return html.Div([
        # Barre d'utilisateur
        html.Div([
            html.Span(f"👤 {session['username']}", style={"float": "right", "marginRight": "20px", "color": SG_RED, "fontWeight": "bold"}),
            html.A("Déconnexion", href="/logout", style={"float": "right", "marginRight": "10px", "color": "#666"})
        ], style={"padding": "10px", "backgroundColor": "#f0f0f0", "marginBottom": "20px"}),
        # Onglets
        dcc.Tabs(
            id="tabs",
            value="home",
            children=[
                dcc.Tab(label="🏠 Accueil", value="home"),
                dcc.Tab(label="📈 Statistiques Générales", value="stats"),
                dcc.Tab(label="📊 Analyses Graphiques", value="viz"),
                dcc.Tab(label="🔍 Détails des commentaires", value="details"),
                dcc.Tab(label="📝 Posts divers", value="posts"),
            ],
            style={"fontWeight": "600", "fontSize": "16px"}
        ),
        html.Div(id="content")
    ])

app.layout = get_layout


# ========================
# 4. Callbacks pour pages
# ========================
@app.callback(
    Output("content", "children"),
    Input("tabs", "value")
)
def render_page(tab):
    global df_postes, absa_df
    
    # === CHARTE GRAPHIQUE SOCIÉTÉ GÉNÉRALE ===
    SG_RED = "#E60000"
    SG_BLACK = "#000000"
    SG_GREY = "#3D3D3D"
    SG_LIGHT_GREY = "#F5F5F5"
    SG_WHITE = "#FFFFFF"
    SG_RED_GRADIENT = "linear-gradient(135deg, #E60000 0%, #A00000 100%)"
    
    # === STYLES PROFESSIONNELS ===
    card_premium = {
        "backgroundColor": SG_WHITE,
        "padding": "35px",
        "borderRadius": "20px",
        "boxShadow": "0 10px 40px rgba(230, 0, 0, 0.08)",
        "marginBottom": "30px",
        "border": f"1px solid {SG_LIGHT_GREY}",
        "transition": "all 0.3s ease"
    }
    
    hero_section = {
        "background": SG_RED_GRADIENT,
        "color": SG_WHITE,
        "padding": "60px 40px",
        "borderRadius": "24px",
        "marginBottom": "50px",
        "boxShadow": "0 20px 60px rgba(230, 0, 0, 0.25)",
        "position": "relative",
        "overflow": "hidden"
    }
    
    filter_premium = {
        "backgroundColor": SG_WHITE,
        "padding": "30px",
        "borderRadius": "20px",
        "marginBottom": "40px",
        "border": f"2px solid {SG_RED}",
        "boxShadow": "0 8px 30px rgba(0, 0, 0, 0.06)"
    }
    
    section_title = {
        "fontSize": "32px",
        "fontWeight": "700",
        "color": SG_BLACK,
        "marginBottom": "15px",
        "letterSpacing": "-0.5px",
        "fontFamily": "'Segoe UI', 'Helvetica Neue', sans-serif"
    }
    
    accent_box = {
        "backgroundColor": SG_LIGHT_GREY,
        "padding": "25px",
        "borderRadius": "16px",
        "borderLeft": f"6px solid {SG_RED}",
        "marginBottom": "20px"
    }
    
    # ==================== PAGE HOME ====================
    if tab == "home":
        return html.Div([
            # Hero Premium avec effet
            html.Div([
                html.Div([
                    html.Div([
                        html.H1("Analyse des sentiments: cas des banques", 
                               style={
                                   "fontSize": "84px", 
                                   "fontWeight": "900",
                                   "marginBottom": "25px",
                                   "letterSpacing": "-3px",
                                   "textShadow": "3px 5px 15px rgba(0,0,0,0.3)",
                                   "fontFamily": "'Segoe UI', 'Helvetica Neue', sans-serif"
                               }),
                        html.Div([
                            html.Span("━━━━━", style={"color": SG_WHITE, "opacity": "0.6", "fontSize": "24px"}),
                        ], style={"marginBottom": "20px"}),
                        html.P("Intelligence d'Analyse de l'Image de Marque", 
                              style={
                                  "fontSize": "28px", 
                                  "opacity": "0.95",
                                  "fontWeight": "300",
                                  "letterSpacing": "1px"
                              }),
                        html.P("Réseaux Sociaux • Analyse de sentiments • Performance Tracking", 
                              style={
                                  "fontSize": "16px", 
                                  "opacity": "0.85",
                                  "marginTop": "15px",
                                  "textTransform": "uppercase",
                                  "letterSpacing": "2px"
                              })
                    ], style={"textAlign": "center"})
                ], style={"position": "relative", "zIndex": "2"})
            ], style=hero_section),

            # Bannière d'information premium
            html.Div([
                html.Div([
                    html.Div("🎯", style={"fontSize": "56px", "marginBottom": "25px"}),
                    html.H3("Plateforme d'Analyse Stratégique", 
                           style={
                               "color": SG_BLACK, 
                               "marginBottom": "20px", 
                               "fontSize": "36px",
                               "fontWeight": "700"
                           }),
                    html.Div([
                        html.P(
                            "Transformez les données sociales en intelligence stratégique. "
                            "Notre plateforme analyse en profondeur les commentaires et interactions "
                            "sur Facebook pour vous offrir une vision 360° de votre réputation digitale.",
                            style={
                                "fontSize": "20px", 
                                "lineHeight": "1.8",
                                "color": SG_GREY,
                                "maxWidth": "900px",
                                "margin": "auto"
                            }
                        )
                    ])
                ], style={**card_premium, "textAlign": "center", "padding": "50px"})
            ], style={"marginBottom": "50px"}),
            
            # Grille de fonctionnalités premium
            html.Div([
                # Feature 1 - Stats
                html.Div([
                    html.Div([
                        html.Div([
                            html.Div("📊", style={"fontSize": "64px", "marginBottom": "25px"}),
                            html.H4("Analytics Avancés", 
                                   style={
                                       "color": SG_RED, 
                                       "marginBottom": "15px",
                                       "fontSize": "24px",
                                       "fontWeight": "700"
                                   }),
                            html.P("KPIs en temps réel, tableaux de bord dynamiques et métriques de performance",
                                  style={
                                      "color": SG_GREY, 
                                      "fontSize": "16px",
                                      "lineHeight": "1.6"
                                  }),
                            html.Div("━━━━", style={"color": SG_RED, "marginTop": "20px", "fontSize": "20px"})
                        ], style={**card_premium, "textAlign": "center", "height": "320px", "display": "flex", "flexDirection": "column", "justifyContent": "center"})
                    ])
                ], style={"width": "31%", "display": "inline-block", "marginRight": "3.5%"}),
                
                # Feature 2 - Sentiment
                html.Div([
                    html.Div([
                        html.Div([
                            html.Div("💭", style={"fontSize": "64px", "marginBottom": "25px"}),
                            html.H4("Analyse de sentiments ", 
                                   style={
                                       "color": SG_RED, 
                                       "marginBottom": "15px",
                                       "fontSize": "24px",
                                       "fontWeight": "700"
                                   }),
                            html.P("Intelligence artificielle pour comprendre émotions, tonalités et perceptions clients",
                                  style={
                                      "color": SG_GREY, 
                                      "fontSize": "16px",
                                      "lineHeight": "1.6"
                                  }),
                            html.Div("━━━━", style={"color": SG_RED, "marginTop": "20px", "fontSize": "20px"})
                        ], style={**card_premium, "textAlign": "center", "height": "320px", "display": "flex", "flexDirection": "column", "justifyContent": "center"})
                    ])
                ], style={"width": "31%", "display": "inline-block", "marginRight": "3.5%"}),
                
                # Feature 3 - Action
                html.Div([
                    html.Div([
                        html.Div([
                            html.Div("🎯", style={"fontSize": "64px", "marginBottom": "25px"}),
                            html.H4("Leviers Stratégiques", 
                                   style={
                                       "color": SG_RED, 
                                       "marginBottom": "15px",
                                       "fontSize": "24px",
                                       "fontWeight": "700"
                                   }),
                            html.P("Recommandations actionnables pour optimiser image de marque et satisfaction client",
                                  style={
                                      "color": SG_GREY, 
                                      "fontSize": "16px",
                                      "lineHeight": "1.6"
                                  }),
                            html.Div("━━━━", style={"color": SG_RED, "marginTop": "20px", "fontSize": "20px"})
                        ], style={**card_premium, "textAlign": "center", "height": "320px", "display": "flex", "flexDirection": "column", "justifyContent": "center"})
                    ])
                ], style={"width": "31%", "display": "inline-block"})
            ], style={"marginBottom": "50px"}),
            
            # Statistiques clés
            html.Div([
                html.Div([
                    html.H4("Performance en Chiffres", 
                           style={
                               "color": SG_BLACK,
                               "fontSize": "28px",
                               "marginBottom": "30px",
                               "fontWeight": "700",
                               "textAlign": "center"
                           }),
                    html.Div([
                        html.Div([
                            html.H3("10K+", style={"color": SG_RED, "fontSize": "48px", "fontWeight": "900", "margin": "0"}),
                            html.P("Commentaires Analysés", style={"color": SG_GREY, "fontSize": "14px", "marginTop": "10px"})
                        ], style={"width": "24%", "display": "inline-block", "textAlign": "center"}),
                        html.Div([
                            html.H3("98%", style={"color": SG_RED, "fontSize": "48px", "fontWeight": "900", "margin": "0"}),
                            html.P("Précision IA", style={"color": SG_GREY, "fontSize": "14px", "marginTop": "10px"})
                        ], style={"width": "24%", "display": "inline-block", "textAlign": "center"}),
                        html.Div([
                            html.H3("24/7", style={"color": SG_RED, "fontSize": "48px", "fontWeight": "900", "margin": "0"}),
                            html.P("Monitoring Continu", style={"color": SG_GREY, "fontSize": "14px", "marginTop": "10px"})
                        ], style={"width": "24%", "display": "inline-block", "textAlign": "center"}),
                        html.Div([
                            html.H3("4.8/5", style={"color": SG_RED, "fontSize": "48px", "fontWeight": "900", "margin": "0"}),
                            html.P("Satisfaction Utilisateur", style={"color": SG_GREY, "fontSize": "14px", "marginTop": "10px"})
                        ], style={"width": "24%", "display": "inline-block", "textAlign": "center"})
                    ])
                ], style={**card_premium, "padding": "50px"})
            ], style={"marginBottom": "50px"}),
            
            # Citation professionnelle
            html.Div([
                html.Div([
                    html.Div("━━━━━━━", style={"color": SG_RED, "fontSize": "32px", "marginBottom": "25px"}),
                    html.P(
                        "\" De la donnée brute à l'intelligence stratégique \"",
                        style={
                            "fontSize": "32px",
                            "fontStyle": "italic",
                            "color": SG_BLACK,
                            "fontWeight": "600",
                            "marginBottom": "20px"
                        }
                    ),
                    html.P(
                        "Prenez des décisions éclairées grâce à l'analyse prédictive",
                        style={
                            "fontSize": "18px",
                            "color": SG_GREY,
                            "fontWeight": "400"
                        }
                    )
                ], style={**card_premium, "textAlign": "center", "padding": "60px", "background": SG_LIGHT_GREY})
            ])
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ==================== PAGE STATS ====================
    elif tab == "stats":
        if df.empty:
            return html.Div([
                html.Div([
                    html.Div("⚠️", style={"fontSize": "100px", "marginBottom": "30px", "opacity": "0.3"}),
                    html.H3("Aucune donnée disponible", 
                           style={"color": SG_GREY, "fontSize": "28px", "fontWeight": "600"})
                ], style={**card_premium, "textAlign": "center", "padding": "80px"})
            ])

        return html.Div([
            # Header élégant
            html.Div([
                html.Div([
                    
                    html.H2("📈 Statistiques Générales", 
                           style={
                               "fontSize": "52px", 
                               "marginBottom": "15px",
                               "fontWeight": "900",
                               "letterSpacing": "-1px"
                           }),
                    html.Div("━━", style={"color": SG_WHITE, "fontSize": "32px", "marginBottom": "15px", "opacity": "0.8"}),
                    html.P("Analyse des performances et métriques clés", 
                          style={"fontSize": "20px", "opacity": "0.9", "fontWeight": "300"})
                ], style={"textAlign": "center"})
            ], style=hero_section),

            # Filtres professionnels
            html.Div([
                html.Div([
                    html.Div("🎛️", style={"fontSize": "28px", "marginBottom": "20px"}),
                    html.H4("Filtres de Sélection", 
                           style={
                               "color": SG_BLACK, 
                               "fontSize": "24px",
                               "fontWeight": "700",
                               "marginBottom": "25px"
                           })
                ]),
                html.Div([
                    html.Div([
                        html.Label("SOURCE", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block", 
                                     "color": SG_RED,
                                     "fontSize": "12px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.Dropdown(
                            id="filtre-source",
                            options=[{"label": s, "value": s} for s in df["source"].unique()],
                            value=list(df["source"].unique()),
                            multi=True,
                            style={"borderRadius": "12px"}
                        )
                    ], style={"width": "48%", "display": "inline-block", "marginRight": "4%"}),
                    
                    html.Div([
                        html.Label("PÉRIODE D'ANALYSE", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block", 
                                     "color": SG_RED,
                                     "fontSize": "12px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.DatePickerRange(
                            id="filtre-date",
                            start_date=dt.date(2025, 1, 1),
                            end_date=df["date"].max().date(),
                            style={"borderRadius": "12px"}
                        )
                    ], style={"width": "48%", "display": "inline-block"})
                ])
            ], style=filter_premium),

            # KPIs Grid
            html.Div(id="stats-metrics", style={"display": "flex", "flexWrap": "wrap", "gap": "25px", "marginBottom": "40px"}),

            # Guide des indicateurs premium
            html.Div([
                html.Div([
                    html.Div([
                        html.Div("📖", style={"fontSize": "32px", "marginRight": "15px", "display": "inline-block"}),
                        html.H4("Guide des Indicateurs", 
                               style={
                                   "color": SG_BLACK, 
                                   "display": "inline-block",
                                   "fontSize": "26px",
                                   "fontWeight": "700",
                                   "verticalAlign": "middle"
                               })
                    ], style={"marginBottom": "30px"}),
                    
                    html.Div([
                        html.Div([
                            html.Div([
                                html.Span("😍😊💕", style={"fontSize": "32px", "marginRight": "20px"}),
                                html.Div([
                                    html.Span("Commentaires Positifs", style={"fontWeight": "700", "fontSize": "18px", "color": SG_BLACK, "display": "block"}),
                                    html.Span("Nombre total de retours favorables sur la période", style={"color": SG_GREY, "fontSize": "14px"})
                                ], style={"display": "inline-block", "verticalAlign": "middle"})
                            ], style=accent_box),
                            
                            html.Div([
                                html.Span("🤬😡🥵", style={"fontSize": "32px", "marginRight": "20px"}),
                                html.Div([
                                    html.Span("Commentaires Négatifs", style={"fontWeight": "700", "fontSize": "18px", "color": SG_BLACK, "display": "block"}),
                                    html.Span("Volume des retours défavorables nécessitant attention", style={"color": SG_GREY, "fontSize": "14px"})
                                ], style={"display": "inline-block", "verticalAlign": "middle"})
                            ], style=accent_box),
                            
                            html.Div([
                                html.Span("📊", style={"fontSize": "32px", "marginRight": "20px"}),
                                html.Div([
                                    html.Span("Ratio de Négativité", style={"fontWeight": "700", "fontSize": "18px", "color": SG_BLACK, "display": "block"}),
                                    html.Span("Pourcentage de sentiments négatifs vs positifs", style={"color": SG_GREY, "fontSize": "14px"})
                                ], style={"display": "inline-block", "verticalAlign": "middle"})
                            ], style=accent_box)
                        ], style={"width": "48%", "display": "inline-block", "marginRight": "4%", "verticalAlign": "top"}),
                        
                        html.Div([
                            html.Div([
                                html.Span("📈", style={"fontSize": "32px", "marginRight": "20px"}),
                                html.Div([
                                    html.Span("Moyenne Quotidienne", style={"fontWeight": "700", "fontSize": "18px", "color": SG_BLACK, "display": "block"}),
                                    html.Span("Flux moyen de commentaires par jour", style={"color": SG_GREY, "fontSize": "14px"})
                                ], style={"display": "inline-block", "verticalAlign": "middle"})
                            ], style=accent_box),
                            
                            html.Div([
                                html.Span("📉", style={"fontSize": "32px", "marginRight": "20px"}),
                                html.Div([
                                    html.Span("Moyenne Négatifs/Jour", style={"fontWeight": "700", "fontSize": "18px", "color": SG_BLACK, "display": "block"}),
                                    html.Span("Taux quotidien de commentaires négatifs", style={"color": SG_GREY, "fontSize": "14px"})
                                ], style={"display": "inline-block", "verticalAlign": "middle"})
                            ], style=accent_box),
                            
                            html.Div([
                                html.Span("⚡", style={"fontSize": "32px", "marginRight": "20px"}),
                                html.Div([
                                    html.Span("Indicateur Clé", style={"fontWeight": "700", "fontSize": "18px", "color": SG_BLACK, "display": "block"}),
                                    html.Span("Métrique de performance globale", style={"color": SG_GREY, "fontSize": "14px"})
                                ], style={"display": "inline-block", "verticalAlign": "middle"})
                            ], style=accent_box)
                        ], style={"width": "48%", "display": "inline-block", "verticalAlign": "top"})
                    ])
                ], style=card_premium)
            ])
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ==================== PAGE VIZ ====================
    elif tab == "viz":
        if df.empty or absa_df.empty:
            return html.Div([
                html.Div([
                    html.Div("⚠️", style={"fontSize": "100px", "marginBottom": "30px", "opacity": "0.3"}),
                    html.H3("Données de visualisation indisponibles", 
                           style={"color": SG_GREY, "fontSize": "28px", "fontWeight": "600"})
                ], style={**card_premium, "textAlign": "center", "padding": "80px"})
            ])

        return html.Div([
            # Header
            html.Div([
                html.Div([
                    
                    html.H2("📊 Visualisations Avancées", 
                           style={
                               "fontSize": "52px", 
                               "marginBottom": "15px",
                               "fontWeight": "900",
                               "letterSpacing": "-1px"
                           }),
                    html.Div("━━", style={"color": SG_WHITE, "fontSize": "32px", "marginBottom": "15px", "opacity": "0.8"}),
                    html.P("Analyse graphique du ressenti et des tendances clients", 
                          style={"fontSize": "20px", "opacity": "0.9", "fontWeight": "300"})
                ], style={"textAlign": "center"})
            ], style=hero_section),

            # Filtres
            html.Div([
                html.Div([
                    html.Div("🎛️", style={"fontSize": "28px", "marginBottom": "20px"}),
                    html.H4("Paramètres de Visualisation", 
                           style={
                               "color": SG_BLACK, 
                               "fontSize": "24px",
                               "fontWeight": "700",
                               "marginBottom": "25px"
                           })
                ]),
                html.Div([
                    html.Div([
                        html.Label("SOURCE DE DONNÉES", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block", 
                                     "color": SG_RED,
                                     "fontSize": "12px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.Dropdown(
                            id="viz-filtre-source",
                            options=[{"label": s, "value": s} for s in absa_df["source"].unique()],
                            value=list(absa_df["source"].unique()),
                            multi=True
                        )
                    ], style={"width": "48%", "display": "inline-block", "marginRight": "4%"}),
                    
                    html.Div([
                        html.Label("PLAGE TEMPORELLE", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block", 
                                     "color": SG_RED,
                                     "fontSize": "12px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.DatePickerRange(
                            id="viz-filtre-date",
                            start_date=dt.date(2025, 1, 1),
                            end_date=df["date"].max().date()
                        )
                    ], style={"width": "48%", "display": "inline-block"})
                ])
            ], style=filter_premium),

            # Graphiques dans cards premium
            html.Div([
                html.Div([
                    html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "15px"}),
                    html.H3("Évolution du Ressenti Clients - SGCI", 
                           style=section_title)
                ]),
                html.Div(id="nouveau-graphique")
            ], style=card_premium),

            html.Div([
                dcc.Graph(id="viz-sentiments")
            ], style=card_premium),

            html.Div([
                html.Div([
                    html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "15px"}),
                    html.H3("Évolution du Proxy NPS", style=section_title),
                    html.P("Net Promoter Score - Indicateur de fidélisation client",
                          style={"color": SG_GREY, "fontSize": "14px", "marginTop": "5px"})
                ]),
                dcc.Graph(id="viz-nps")
            ], style=card_premium),

            html.Div([
                html.Div([
                    html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "15px"}),
                    html.H3("Répartition par Typologie et Établissement", style=section_title),
                    html.P("Distribution comparative des commentaires par catégorie",
                          style={"color": SG_GREY, "fontSize": "14px", "marginTop": "5px"})
                ]),
                dcc.Graph(id="viz-aspects")
            ], style=card_premium),

            html.Div([
                html.Div([
                    html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "20px", "textAlign": "center"}),
                    html.H3("Nuage Sémantique - Commentaires Négatifs SGCI", 
                           style={**section_title, "textAlign": "center"}),
                    html.P("Analyse lexicale des termes les plus fréquents dans les retours négatifs",
                          style={"color": SG_GREY, "fontSize": "14px", "marginTop": "5px", "textAlign": "center", "marginBottom": "30px"})
                ]),
                html.Div([
                    html.Img(
                        src="data:image/png;base64," + wordcloud_base64,
                        style={
                            "width": "80%", 
                            "display": "block",
                            "margin": "auto",
                            "borderRadius": "16px",
                            "boxShadow": "0 8px 30px rgba(230, 0, 0, 0.15)",
                            "border": f"3px solid {SG_LIGHT_GREY}"
                        }
                    ) if wordcloud_base64 else html.Div([
                        html.P("📊", style={"fontSize": "64px", "marginBottom": "15px", "opacity": "0.3"}),
                        html.P("Visualisation en cours de génération", 
                              style={"color": SG_GREY, "fontSize": "18px"})
                    ], style={"textAlign": "center", "padding": "60px"})
                ])
            ], style=card_premium)
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ==================== PAGE DETAILS ====================
    elif tab == "details":
        absa_df["date"] = absa_df["date"].sort_values(ascending=False)
        if absa_df.empty:
            return html.Div([
                html.Div([
                    html.Div("⚠️", style={"fontSize": "100px", "marginBottom": "30px", "opacity": "0.3"}),
                    html.H3("Aucun commentaire disponible", 
                           style={"color": SG_GREY, "fontSize": "28px", "fontWeight": "600"})
                ], style={**card_premium, "textAlign": "center", "padding": "80px"})
            ])

        return html.Div([
            # Header
            html.Div([
                html.Div([
                    
                    html.H2("🔍 Exploration Détaillée", 
                           style={
                               "fontSize": "52px", 
                               "marginBottom": "15px",
                               "fontWeight": "900",
                               "letterSpacing": "-1px"
                           }),
                    html.Div("━━", style={"color": SG_WHITE, "fontSize": "32px", "marginBottom": "15px", "opacity": "0.8"}),
                    html.P("Analyse granulaire des commentaires par typologie", 
                          style={"fontSize": "20px", "opacity": "0.9", "fontWeight": "300"})
                ], style={"textAlign": "center"})
            ], style=hero_section),

            # Filtres avancés 
            html.Div([
                html.Div([
                    html.Div("🎛️", style={"fontSize": "28px", "marginBottom": "20px"}),
                    html.H4("Filtres de Recherche Avancés", 
                           style={
                               "color": SG_BLACK, 
                               "fontSize": "24px",
                               "fontWeight": "700",
                               "marginBottom": "25px"
                           })
                ]),
                html.Div([
                    # Date
                    html.Div([
                        html.Label("DATE", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block",
                                     "color": SG_RED,
                                     "fontSize": "11px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.Dropdown(
                            id="details-date",
                           options=[{"label": "Toutes", "value": "Toutes"}] +
                                    [{"label": d, "value": d} for d in sorted(absa_df['date'].unique(), reverse=True)],
                            value="Toutes",
                            clearable=False
                        )
                    ], style={"width": "23%", "display": "inline-block", "marginRight": "2.5%"}),

                    # Source
                    html.Div([
                        html.Label("SOURCE", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block",
                                     "color": SG_RED,
                                     "fontSize": "11px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.Dropdown(
                            id="details-source",
                            options=[{"label": "Toutes", "value": "Toutes"}] +
                                    [{"label": s, "value": s} for s in sorted(absa_df['source'].unique())],
                            value="Toutes",
                            clearable=False
                        )
                    ], style={"width": "23%", "display": "inline-block", "marginRight": "2.5%"}),

                    # Aspect
                    html.Div([
                        html.Label("TYPOLOGIE", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block",
                                     "color": SG_RED,
                                     "fontSize": "11px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.Dropdown(
                            id="details-aspect",
                            options=[{"label": "Toutes", "value": "Toutes"}] +
                                    [{"label": a, "value": a} for a in sorted(absa_df['aspect'].unique())],
                            value="Toutes",
                            clearable=False
                        )
                    ], style={"width": "23%", "display": "inline-block", "marginRight": "2.5%"}),

                    # Sentiment
                    html.Div([
                        html.Label("SENTIMENT", 
                                 style={
                                     "fontWeight": "700", 
                                     "marginBottom": "12px", 
                                     "display": "block",
                                     "color": SG_RED,
                                     "fontSize": "11px",
                                     "letterSpacing": "1.5px"
                                 }),
                        dcc.Dropdown(
                            id="details-sentiment",
                            options=[
                                {"label": "Tous", "value": "Tous"},
                                {"label": "😊 Positif", "value": "positif"},
                                {"label": "😡 Négatif", "value": "negatif"}
                            ],
                            value="Tous",
                            clearable=False
                        )
                    ], style={"width": "23%", "display": "inline-block"})
                ])
            ], style=filter_premium),

            # Table des résultats
            html.Div([
                html.Div([
                    html.Div("━━", style={"color": SG_RED, "fontSize": "24px", "marginBottom": "15px"}),
                    html.H4("Résultats de la Recherche", 
                           style={
                               "color": SG_BLACK, 
                               "fontSize": "26px",
                               "fontWeight": "700",
                               "marginBottom": "10px"
                           }),
                    html.P("Commentaires filtrés selon vos critères de sélection",
                          style={"color": SG_GREY, "fontSize": "14px", "marginBottom": "25px"})
                ]),
                dash_table.DataTable(
                    id="details-table",
                    columns=[{"name": i, "id": i} for i in absa_df[["date", "auteur", "phrase", "aspect"]].columns],
                    page_size=10,
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "textAlign": "left", 
                        "padding": "16px",
                        "fontFamily": "'Segoe UI', 'Helvetica Neue', sans-serif",
                        "fontSize": "14px"
                    },
                    style_header={
                        "backgroundColor": SG_BLACK,
                        "color": SG_WHITE,
                        "fontWeight": "700",
                        "fontSize": "13px",
                        "padding": "16px",
                        "textTransform": "uppercase",
                        "letterSpacing": "1px",
                        "border": "none"
                    },
                    style_data={
                        "border": "none",
                        "borderBottom": f"1px solid {SG_LIGHT_GREY}"
                    },
                    style_data_conditional=[
                        {
                            "if": {"row_index": "odd"},
                            "backgroundColor": "#FAFAFA"
                        },
                        {
                            "if": {"row_index": "even"},
                            "backgroundColor": SG_WHITE
                        }
                    ]
                )
            ], style=card_premium)
        ], style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})

    # ==================== PAGE POSTS ====================
    elif tab == "posts":
        if df_postes.empty:
            return html.Div([
                html.Div([
                    html.Div("⚠️", style={"fontSize": "80px", "marginBottom": "20px", "opacity": "0.5"}),
                    html.H3("Aucun post trouvé", style={"color": "#6b7280", "fontWeight": "600"})
                ], style={**card_premium, "textAlign": "center", "padding": "60px"})
            ])

        # Nettoyage des dates
        df_postes["date_post"] = pd.to_datetime(df_postes["date_post"], errors="coerce").dt.date
        df_postes = df_postes.dropna(subset=["date_post"])

        # Contenu principal
        content = [
            # ===== Hero =====
            html.Div([
                
                html.H2("📝 Posts Récents", 
                       style={"fontSize": "42px", "marginBottom": "10px"}),
                html.Div("━━", style={"color": SG_WHITE, "fontSize": "32px", "marginBottom": "15px", "opacity": "0.8"}),
                html.P("Dans le groupe ( Observatoire Libre des Banques )", 
                      style={"fontSize": "18px", "opacity": "0.9", "fontWeight": "300"})
            ], style={**hero_section, "textAlign": "center", "padding": "40px"})

        ]

        # ===== Posts par Source =====
        for source in df_postes["source"].unique():
            content.append(
                html.Div([
                    html.H3(f"📢 {source}", 
                           style={"color": "#c30b0b", "fontSize": "28px", "marginBottom": "20px", "fontWeight": "700"})
                ], style={"marginTop": "40px"})
            )

            # Posts uniques pour chaque source
            posts = df_postes[df_postes["source"] == source].groupby("poste").first().reset_index()
            posts = posts.sort_values(by="date_post", ascending=False)

            for _, row in posts.iterrows():
                # Posts individuels
                coms = df_postes[(df_postes["source"] == source) & (df_postes["poste"] == row["poste"])]

                post_card = html.Div([
                    # Header
                    html.Div([
                        html.Div([
                            html.Span("📅", style={"fontSize": "18px", "marginRight": "6px"}),
                            html.Span(str(row["date_post"]), style={"fontWeight": "600", "color": "#0f0f10"})
                        ], style={"marginBottom": "8px"}),

                        html.Div([
                            html.Span("👤", style={"fontSize": "18px", "marginRight": "6px"}),
                            html.Span(row["auteur"], style={"fontWeight": "600", "color": "#374151"})
                        ], style={"marginBottom": "12px"}),

                        # Contenu du post
                        html.P(row["poste"], 
                              style={
                                  "fontSize": "16px", 
                                  "lineHeight": "1.6",
                                  "color": "#1f2937",
                                  "padding": "15px",
                                  "backgroundColor": "#f9fafb",
                                  "borderRadius": "8px",
                                  "borderLeft": "4px solid #667eea"
                              })
                    ]),

                    # Commentaires liés
                    html.Div([
                        # coms := df_postes[(df_postes["source"] == source) & (df_postes["poste"] == row["poste"])],
                        html.Div([
                            html.H5("💬 Commentaires", 
                                   style={"color": "#374151", "marginTop": "20px", "marginBottom": "15px", "fontWeight": "700"}),

                            dash_table.DataTable(
                                data=coms[["date", "auteur_com", "commentaire"]].to_dict("records"),
                                columns=[{"name": i, "id": i} for i in ["date", "auteur_com", "commentaire"]],
                                page_size=5,
                                style_table={"overflowX": "auto"},
                                style_cell={
                                    "textAlign": "left", 
                                    "padding": "10px",
                                    "fontFamily": "Arial, sans-serif",
                                    "fontSize": "14px",
                                    "whiteSpace": "normal",
                                    "height": "auto"
                                },
                                style_header={
                                    "backgroundColor": "#0a0a0c",
                                    "color": "white",
                                    "fontWeight": "bold"
                                }
                            ) if not coms.empty else html.P(
                                "Aucun commentaire associé", 
                                style={"fontStyle": "italic", "color": "#9ca3af", "marginTop": "5px"}
                            )
                        ])
                    ])
                ], style=card_premium)

                content.append(post_card)

 # séparation entre posts
        return html.Div(content, style={"padding": "50px 30px", "backgroundColor": "#FAFAFA", "minHeight": "100vh"})
    
@app.callback(
    Output("stats-metrics", "children"),
    Input("filtre-source", "value"),
    Input("filtre-date", "start_date"),
    Input("filtre-date", "end_date")
)

def maj_stats(sources, start_date, end_date):
    if not sources:
        return [html.P("⚠️ Aucune source sélectionnée.")]

        # Filtrage
    dff = df[df["source"].isin(sources)]
    dff = dff[(dff["date"].dt.date >= pd.to_datetime(start_date).date()) &
                (dff["date"].dt.date <= pd.to_datetime(end_date).date())]

    if dff.empty:
            return [html.P("⚠️ Aucune donnée après filtrage.")]

        # Calculs
    total_counts = dff.groupby("source").size()
    pos_counts = dff[dff["sentiment"] == "POSITIVE"].groupby("source").size()
    neg_counts = dff[dff["sentiment"] == "NEGATIVE"].groupby("source").size()

    all_dates = pd.date_range(start=dff["date"].min().date(), end=dff["date"].max().date(), freq="D")
    multi_index = pd.MultiIndex.from_product([all_dates, dff["source"].unique()], names=["date", "source"])

    daily_counts = dff.groupby([dff["date"].dt.date, "source"]).size().reindex(multi_index, fill_value=0).unstack()
    daily_neg_counts = dff[dff["sentiment"] == "NEGATIVE"].groupby([dff["date"].dt.date, "source"]).size().reindex(multi_index, fill_value=0).unstack()

    avg_comments = round(daily_counts.mean(), 2)
    avg_neg = round(daily_neg_counts.mean(), 2)
    neg_ratio = round((avg_neg / avg_comments * 100).fillna(0), 2)

        # Affichage des métriques (cartes flexbox)
    metrics = []
    for src in total_counts.index:
        metrics.append(html.Div([
                html.H4(f"Commentaires {src}"),
                html.P(f"Total: {total_counts[src]}"),
                html.P(f"😍😊💕: {pos_counts.get(src, 0)}"),
                html.P(f"🤬😡🥵: {neg_counts.get(src, 0)}"),
                html.P(f"% Négatifs: {neg_ratio.get(src, 0)}%"),
                html.P(f"Moy./jour: {avg_comments[src]}"),
                html.P(f"Moy.Négatifs/jour: {avg_neg[src]}")
            ], style={"border": "1px solid #ccc", "padding": "10px", "margin": "5px"}))

    return metrics

# === Callback interconnecté avec clics ===
@app.callback(
    [Output("viz-sentiments", "figure"),
     Output("viz-nps", "figure"),
     Output("viz-aspects", "figure")],
    [Input("viz-filtre-source", "value"),
     Input("viz-filtre-date", "start_date"),
     Input("viz-filtre-date", "end_date")]
)
def maj_viz(sources, start_date, end_date):
    global absa_df  
    
    if not sources:
        return {}, {}, {}

    # Filtrage par source et date
    dff = df[df["source"].isin(sources)]
    dff = dff[(dff["date"].dt.date >= pd.to_datetime(start_date).date()) &
              (dff["date"].dt.date <= pd.to_datetime(end_date).date())]

    absa_filtered = absa_df[(absa_df["date"].dt.date >= pd.to_datetime(start_date).date()) &
                            (absa_df["date"].dt.date <= pd.to_datetime(end_date).date())]

    if dff.empty or absa_filtered.empty:
        return {}, {}, {}

    # === Graphique sentiments ===
    tot_count = absa_filtered[absa_filtered['source']== "page_sgci"].groupby(
        ['date', 'sentiment']
    ).size().reset_index(name='tot_count')

    couleurs_fixes = {"negatif": "red", "positif": "green"}
    fig_sentiments = px.bar(
        tot_count, x="date", y="tot_count", color="sentiment",
        barmode="group", color_discrete_map=couleurs_fixes
    )

    # === Proxy NPS ===
    all_dates = pd.date_range(start=dff["date"].min().date(), end=dff["date"].max().date(), freq="D")
    multi_index = pd.MultiIndex.from_product([all_dates, dff["source"].unique()], names=["date", "source"])

    daily_counts = dff.groupby([dff["date"].dt.date, "source"]).size().reindex(multi_index, fill_value=0).unstack()
    daily_neg_counts = dff[dff["sentiment"] == "NEGATIVE"].groupby([dff["date"].dt.date, "source"]).size().reindex(multi_index, fill_value=0).unstack()

    detra = daily_neg_counts / daily_counts.replace(0, np.nan)
    promo = 1 - detra
    nps = promo - detra
    nps_reset = nps.reset_index().melt(id_vars="date", var_name="source", value_name="Proxy NPS").dropna()

    fig_nps = px.line(nps_reset, x="date", y="Proxy NPS", color="source")
    fig_nps.add_hline(y=0, line_dash="solid", line_color="black", line_width=2)

    # === Graphique aspects ===
    absa_grouped = absa_filtered[absa_filtered["source"].isin(sources)].groupby(
        ["source", "aspect", "sentiment"]
    ).size().reset_index(name="count")

    fig_aspects = px.bar(
        absa_grouped, x="aspect", y="count", color="sentiment",
        barmode="group", facet_col="source",
        color_discrete_map={"negatif": "red", "positif": "green"},
        labels={"aspect": "Typologie", "count": "Nombre"}
    )

    return fig_sentiments, fig_nps, fig_aspects

@app.callback(
    Output("nouveau-graphique", "children"),
    [Input("viz-sentiments", "clickData"),
     Input("viz-filtre-source", "value")]
)
def creer_nouveau_graph(clickData, sources):
    if not clickData or not sources:
        return html.Div("📌 Cliquez sur une barre pour afficher plus de details contextuels")

    # Récupère la date cliquée
    selected_date = clickData['points'][0]['x']
    filtered_absa = absa_df[(absa_df['source']=="page_sgci") & (absa_df['date'] == selected_date)]

    if filtered_absa.empty:
        return html.Div(f"Aucun commentaire trouvé pour le {selected_date}.")

    # Regrouper par aspect
    aspect_count = filtered_absa.groupby('aspect').size().reset_index(name='nb_commentaires')

    # Crée un nouveau graphique
    fig_aspects = px.bar(aspect_count, x='aspect', y='nb_commentaires', 
                         title=f"Commentaires par typologie le {selected_date}",
                         labels={'aspect': 'Typologie', 'nb_commentaires': 'Nombre de commentaires'},
                         text='nb_commentaires',color_discrete_sequence=["#8B0000"] )
    fig_aspects.update_traces(
    #  textposition='outside',
    textfont=dict(color='black', size=14, family='Arial', weight='bold')
    )

    return dcc.Graph(figure=fig_aspects)


@app.callback(
    Output("details-table", "data"),
    [Input("details-date", "value"),
     Input("details-source", "value"),
     Input("details-aspect", "value"),
     Input("details-sentiment", "value")]
)
def filter_details(date_filter, source_filter, aspect_filter, sentiment_filter):
    filtered_df = absa_df.copy()

    # Appliquer les filtres
    if source_filter != "Toutes":
        filtered_df = filtered_df[filtered_df['source'] == source_filter]
    if aspect_filter != "Toutes":
        filtered_df = filtered_df[filtered_df['aspect'] == aspect_filter]
    if sentiment_filter != "Tous":
        filtered_df = filtered_df[filtered_df['sentiment'] == sentiment_filter]
    if date_filter != "Toutes":
        filtered_df = filtered_df[filtered_df["date"] == date_filter]

    # Trier par date décroissante (plus récentes en premier)
    filtered_df = filtered_df.sort_values(by="date", ascending=False)

    return filtered_df[["date", "auteur", "phrase", "aspect"]].to_dict("records")


# 5. Lancement

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8053))
    app.run(debug=False, host="0.0.0.0", port=port)


# # ----------- PAGE CHATBOT --------
# elif page == "🤖 Chatbot IA":
#     st.title("🤖 Assistant Marketing IA")

#     # ---- État de la conversation ----
#     if "chat_history" not in st.session_state:
#         st.session_state.chat_history = []

#     # Zone de saisie utilisateur
#     user_input = st.chat_input("💬 Posez votre question :")

#     if user_input:
#         # Stocker immédiatement la question de l’utilisateur
#         st.session_state.chat_history.append(("user", user_input))
        
#         # Générer une réponse contextualisée (toujours en français)
#         prompt = f"""
#         Tu es un assistant virtuel spécialisé en **marketing bancaire et digital**. 
#         Tes réponses doivent être **en français**, claires et pédagogiques. 
#         Sois structuré et donne des exemples concrets quand c’est pertinent. 
#         Voici la question de l’utilisateur : {user_input}
#         """

#         response = query_llama(prompt)

#         # Stocker la réponse
#         st.session_state.chat_history.append(("assistant", response))

#     # Affichage du chat avec bulles
#     for role, msg in st.session_state.chat_history:
#         if role == "user":
#             with st.chat_message("user"):
#                 st.markdown(msg)
#         else:
#             with st.chat_message("assistant"):
#                 st.markdown(msg)


