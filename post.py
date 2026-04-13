import time
import json
import re
import random
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, NoSuchElementException
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from unidecode import unidecode
import requests
from PIL import Image
from io import BytesIO
import pytesseract

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
GROUP_URL = "https://www.facebook.com/groups/656390831772336"
MAX_SCROLL_ATTEMPTS = 20
SCROLL_WAIT_TIME = 3
COMMENT_LOAD_WAIT = 4
OUTPUT_FILE = "postes.csv"

MOTS_CLES = [
    "sgci", "SGBCI", "SGCi", "société générale", "la générale", "sgbci",
    "societe generale", "la generale", "#SGCI", "#sgci", "la general",
    "#sociétéGénérale", "SGCONNECT", "SG CONNECT", "sgconnect", "Société générale"
]

# ─────────────────────────────────────────────
# INITIALISATION DU NAVIGATEUR
# ─────────────────────────────────────────────
options = EdgeOptions()
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-infobars")
options.add_argument("--lang=fr-FR")
# User-agent Edge 133 (mars 2026)
options.add_argument(
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"
)
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver_path = "./edgedriver_win64/msedgedriver.exe"
driver = webdriver.Edge(
    service=EdgeService(executable_path=driver_path),
    options=options
)

# Masquer navigator.webdriver (anti-détection 2026)
driver.execute_cdp_cmd(
    "Page.addScriptToEvaluateOnNewDocument",
    {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
)

# Chargement des données existantes
try:
    data_existante = pd.read_csv(OUTPUT_FILE)
    print(f"📂 {len(data_existante)} lignes existantes chargées")
except FileNotFoundError:
    data_existante = pd.DataFrame()
    print("📂 Nouveau fichier CSV sera créé")


# ─────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────
def human_delay(min_s=1.0, max_s=3.0):
    """Délai aléatoire pour simuler un comportement humain"""
    time.sleep(random.uniform(min_s, max_s))


def nettoyer_texte(texte: str) -> str:
    """Normalise un texte pour la comparaison"""
    texte = unidecode(texte).lower()
    texte = re.sub(r'[^\w\s]', ' ', texte)
    texte = re.sub(r'\s+', ' ', texte).strip()
    return texte


def contient_mot_cle(texte: str) -> bool:
    """Vérifie la présence d'un mot-clé dans le texte"""
    texte_clean = nettoyer_texte(texte)
    return any(nettoyer_texte(mot) in texte_clean for mot in MOTS_CLES)


# ─────────────────────────────────────────────
# AUTHENTIFICATION
# ─────────────────────────────────────────────
def load_cookies() -> bool:
    """Charge et injecte les cookies Facebook"""
    try:
        driver.get("https://www.facebook.com/")
        time.sleep(3)

        with open("facebook_cookies.json", "r", encoding="utf-8") as f:
            cookies = json.load(f)

        print(f"📁 {len(cookies)} cookies chargés")

        for cookie in cookies:
            # Nettoyer les attributs non supportés par Selenium
            for key in ["sameSite", "storeId", "id", "hostOnly", "session", "expirationDate"]:
                cookie.pop(key, None)
            # Correction du domaine (compatibilité 2026)
            if "domain" in cookie and not cookie["domain"].startswith("."):
                cookie["domain"] = "." + cookie["domain"].lstrip(".")
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"  ⚠️ Cookie ignoré ({cookie.get('name', '?')}): {e}")

        print("✅ Cookies injectés")
        return True

    except FileNotFoundError:
        print("❌ facebook_cookies.json introuvable !")
        return False
    except Exception as e:
        print(f"❌ Erreur cookies : {e}")
        return False


def verify_login() -> bool:
    """Vérifie que la session Facebook est active"""
    login_indicators = [
        "//input[@name='email']",
        "//input[@name='pass']",
    ]
    for indicator in login_indicators:
        if driver.find_elements(By.XPATH, indicator):
            return False
    return True


# ─────────────────────────────────────────────
# CHARGEMENT DE PAGE
# ─────────────────────────────────────────────
def wait_for_page_load(timeout=60):
    """Attend le chargement complet de la page"""
    print("🔄 Chargement de la page...")
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        print("⚠️ Timeout readyState")

    # Sélecteurs stables 2026 : role= et data-pagelet=
    stable_selectors = [
        "div[role='main']",
        "div[role='feed']",
        "div[data-pagelet='GroupFeed']",
        "div[data-pagelet='ProfileTimeline']",
        "div[role='article']",
    ]
    for sel in stable_selectors:
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            print(f"✅ Page prête ({sel})")
            return
        except TimeoutException:
            continue

    print("⚠️ Sélecteur principal non trouvé — on continue")
    human_delay(2, 4)


# ─────────────────────────────────────────────
# CONVERSION DE DATES
# ─────────────────────────────────────────────
def convertir_date_facebook(date_str: str) -> str:
    """
    Convertit une date relative ou absolue Facebook en JJ-MM-AAAA.
    Supporte : FR, EN, timestamps ISO 8601 (attribut datetime=).
    """
    aujourd_hui = datetime.today()
    s = date_str.lower().strip()

    MOIS_FR = {
        "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12
    }

    try:
        # Timestamp ISO 8601 ex: "2024-05-10T14:30:00+0000"
        iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        if iso_match:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d").strftime("%d-%m-%Y")

        # "hier" / "yesterday"
        if "hier" in s or "yesterday" in s:
            return (aujourd_hui - timedelta(days=1)).strftime("%d-%m-%Y")

        # "aujourd" / "today" / "just now" / "à l'instant"
        if any(k in s for k in ["aujourd", "today", "just now", "instant"]):
            return aujourd_hui.strftime("%d-%m-%Y")

        # Minutes
        if re.search(r"\d+\s*m(in)?", s):
            m = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(minutes=m)).strftime("%d-%m-%Y")

        # Heures
        if re.search(r"\d+\s*(h|hr|heure)", s):
            h = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(hours=h)).strftime("%d-%m-%Y")

        # Jours
        if re.search(r"\d+\s*(j|d|jour|day)", s):
            d = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(days=d)).strftime("%d-%m-%Y")

        # Semaines
        if re.search(r"\d+\s*(sem|w|week)", s):
            w = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(weeks=w)).strftime("%d-%m-%Y")

        # Mois
        if re.search(r"\d+\s*(mois|mo|month)", s):
            mo = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(days=mo * 30)).strftime("%d-%m-%Y")

        # Années
        if re.search(r"\d+\s*(an|ans|y|year)", s):
            y = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(days=y * 365)).strftime("%d-%m-%Y")

        # Date absolue : "10 mai", "10 mai 2024", "10 mai à 14:30"
        s_clean = re.sub(r"\s*à\s*\d{1,2}:\d{2}", "", s).strip()
        parts = s_clean.split()
        if len(parts) >= 2:
            try:
                jour = int(parts[0])
                mois_str = unidecode(parts[1]).lower()
                mois_num = MOIS_FR.get(mois_str)
                annee = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else aujourd_hui.year
                if mois_num:
                    return datetime(annee, mois_num, jour).strftime("%d-%m-%Y")
            except (ValueError, IndexError):
                pass

        return "Format inconnu"

    except Exception:
        return "Erreur conversion"


# ─────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────
def extract_text_from_image_url(image_url: str) -> str:
    """OCR sur une image depuis son URL"""
    try:
        print(f"  🖼️ OCR: {image_url[:60]}...")
        response = requests.get(image_url, timeout=10)
        if response.status_code != 200:
            return ""
        image = Image.open(BytesIO(response.content)).convert('L')
        text = pytesseract.image_to_string(image, lang='fra+eng')
        return nettoyer_texte(text)
    except Exception as e:
        print(f"  ⚠️ Erreur OCR: {e}")
        return ""


# ─────────────────────────────────────────────
# EXTRACTION DES POSTS
# ─────────────────────────────────────────────
def extraire_texte_post(post) -> str | None:
    """
    Extraction robuste du texte d'un post.
    2026 : priorité aux attributs data-* stables, fallback sur dir='auto'.
    Classes CSS hachées supprimées (instables).
    """
    # Sélecteurs stables par ordre de priorité
    SELECTEURS = [
        "div[data-ad-comet-preview='message']",    # le plus stable
        "div[data-ad-preview='message']",
        "div[data-testid='post_message']",
        "div[dir='auto']",                          # fallback sémantique
        "span[dir='auto']",
    ]

    textes = []
    for sel in SELECTEURS:
        try:
            elements = post.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                t = el.text.strip()
                if t and len(t) > 10:
                    textes.append(t)
        except Exception:
            continue

    if textes:
        texte_final = max(textes, key=len)
        print(f"  ✅ Texte extrait ({len(texte_final)} car.)")
        return texte_final

    print("  ⚠️ Aucun texte trouvé")
    return None


def cliquer_voir_plus(post) -> bool:
    """Clique sur 'Voir plus' / 'En voir plus' si présent"""
    try:
        voir_plus = post.find_element(
            By.XPATH,
            ".//div[@role='button' and ("
            "contains(., 'Voir plus') or "
            "contains(., 'En voir plus') or "
            "contains(., 'See more')"
            ")]"
        )
        if voir_plus.is_displayed():
            driver.execute_script("arguments[0].click();", voir_plus)
            human_delay(0.8, 1.5)
            print("  📌 'Voir plus' cliqué")
            return True
    except Exception:
        pass
    return False


def extraire_auteur_date(post):
    """
    Extrait l'auteur et la date d'un post.
    2026 : priorité à l'attribut datetime= de <time> pour la date.
    """
    date_formatee = None
    auteur = "Auteur inconnu"

    # ── Date : balise <time datetime=> (le plus fiable en 2026) ──
    try:
        time_el = post.find_element(By.CSS_SELECTOR, "time[datetime]")
        raw_date = time_el.get_attribute("datetime") or time_el.text.strip()
        date_formatee = convertir_date_facebook(raw_date)
    except Exception:
        # Fallback : lien permalink avec texte relatif
        try:
            date_el = post.find_element(
                By.XPATH,
                ".//a[contains(@href, '/posts/') or contains(@href, '/permalink/')]"
            )
            date_formatee = convertir_date_facebook(date_el.text.strip())
        except Exception:
            date_formatee = "Date inconnue"

    # ── Auteur : sélecteurs sémantiques stables ──
    SELECTEURS_AUTEUR = [
        "h2 a span",
        "h3 a span",
        "strong a",
        "a[role='link'] span[dir='auto']",
        # Dernier recours : premier lien de profil dans l'article
        "a[href*='facebook.com/'][role='link']",
    ]
    for sel in SELECTEURS_AUTEUR:
        try:
            el = post.find_element(By.CSS_SELECTOR, sel)
            nom = el.text.strip().split("·")[0].strip()
            if nom and len(nom) > 2:
                auteur = nom
                break
        except Exception:
            continue

    print(f"  📆 {date_formatee} — 👤 {auteur}")
    return date_formatee, auteur


def analyser_images_post(post) -> bool:
    """Analyse les images d'un post avec OCR pour détecter les mots-clés"""
    try:
        images = post.find_elements(By.TAG_NAME, "img")
        print(f"  🖼️ {len(images)} image(s) à analyser...")

        for img in images:
            src = img.get_attribute("src") or ""
            # Filtrer les icônes et avatars
            if not src or any(x in src for x in ["emoji", "static.xx.fbcdn", "rsrc.php"]):
                continue
            if "scontent" not in src:
                continue

            ocr_text = extract_text_from_image_url(src)
            if ocr_text and contient_mot_cle(ocr_text):
                print("  ✅ Mot-clé détecté dans image !")
                return True

        return False

    except Exception as e:
        print(f"  ⚠️ Erreur analyse images: {e}")
        return False


# ─────────────────────────────────────────────
# GESTION DES COMMENTAIRES
# ─────────────────────────────────────────────
def ouvrir_commentaires(post) -> bool:
    """
    Ouvre le panneau de commentaires.
    Sélecteurs confirmés par diagnostic (mars 2026) :
      1. aria-label='Commenter'        → bouton barre de réaction
      2. aria-label='X commentaires'   → compteur cliquable
    """
    btn = None

    # ── Priorité 1 : aria-label='Commenter' ────────────────────────
    try:
        btn = post.find_element(By.CSS_SELECTOR, "[aria-label='Voir plus de commentaires']")
    except Exception:
        pass

    # ── Priorité 2 : aria-label contenant 'commentaire(s)' ─────────
    if not btn:
        try:
            candidates = post.find_elements(
                By.XPATH,
                ".//*[contains(@aria-label,'commentaire') or "
                "contains(@aria-label,'commentaires') or "
                "contains(@aria-label,'Voir plus de commentaires') or "
                "contains(@aria-label,'réponses') or "
                "contains(@aria-label,'Voir 1 réponse') or "
                "contains(@aria-label,'Voir les x réponses') or "
                "contains(@aria-label,'Comment') or "
                "contains(@aria-label,'Comments') or "
                "contains(@aria-label,'comments') or "
                "contains(@aria-label,'comment')]"
            )
            for c in candidates:
                lbl = (c.get_attribute("aria-label") or "").lower()
                if ("comment" in lbl
                        and "rédiger" not in lbl
                        and "écrire" not in lbl
                        and "écrivez" not in lbl
                        and "write" not in lbl):
                    btn = c
                    break
        except Exception:
            pass

    # ── Priorité 3 : texte visible "commentaire(s)" ─────────────────
    if not btn:
        try:
            candidates = post.find_elements(
                By.XPATH,
                ".//*[(self::span or self::div) and @role='button' and ("
                "contains(translate(normalize-space(.),"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                "'commentaires') or "
                "contains(translate(normalize-space(.),"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                "'comments'))]"
            )
            for c in candidates:
                txt = (c.text or "").lower()
                if "comment" in txt and "rédiger" not in txt:
                    btn = c
                    break
        except Exception:
            pass

    if not btn:
        print("  ⚠️ Bouton commentaires introuvable")
        return False

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    human_delay(0.5, 1.0)
    driver.execute_script("arguments[0].click();", btn)
    human_delay(COMMENT_LOAD_WAIT - 0.5, COMMENT_LOAD_WAIT + 1)
    print("  💬 Panneau commentaires ouvert")
    return True


def trouver_container_commentaires():
    """
    Trouve le container de commentaires.
    2026 : utilise role= et data-* — les classes CSS hachées sont supprimées.
    """
    SELECTEURS = [
        "div[role='dialog']",                               # Popup / modal
        "div[data-visualcompletion='ignore-dynamic']",     # Section dynamique stable
        "ul[data-visualcompletion='ignore-dynamic']",
        "div[role='main'] div[role='article'] div[role='article']",  # Articles imbriqués
    ]

    for sel in SELECTEURS:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            container = driver.find_element(By.CSS_SELECTOR, sel)
            print(f"  ✅ Container trouvé : {sel[:60]}")
            return container
        except (TimeoutException, NoSuchElementException):
            continue

    print("  ❌ Container commentaires introuvable")
    return None


def scroll_commentaires(container):
    """Scroll le container de commentaires jusqu'à stabilité"""
    print("  🔄 Scroll des commentaires...")
    prev_count = 0
    stale_rounds = 0

    for _ in range(10):  # max 10 passes
        try:
            items = container.find_elements(By.CSS_SELECTOR, "div[role='article']")
            current_count = len(items)
        except StaleElementReferenceException:
            print("  ⚠️ Container périmé — arrêt scroll")
            break

        if current_count == prev_count:
            stale_rounds += 1
            if stale_rounds >= 2:
                print(f"  ✅ Stable : {current_count} éléments")
                break
        else:
            stale_rounds = 0
            prev_count = current_count
            print(f"    📊 {current_count} commentaires visibles")

        # Scroll dans le container
        try:
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;", container
            )
        except Exception:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        human_delay(COMMENT_LOAD_WAIT - 0.5, COMMENT_LOAD_WAIT + 0.5)

        # Cliquer sur "Afficher plus de commentaires"
        try:
            more_btns = driver.find_elements(
                By.XPATH,
                "//div[@role='button' and ("
                "contains(., 'Afficher plus') or "
                "contains(., 'View more') or "
                "contains(., 'Voir plus de commentaires') or "
                "contains(., 'More comments')"
                ")]"
            )
            for mb in more_btns:
                if mb.is_displayed():
                    driver.execute_script("arguments[0].click();", mb)
                    human_delay(1.5, 2.5)
                    break
        except Exception:
            pass


def extraire_commentaires(container) -> list:
    """
    Extraction robuste des commentaires.
    2026 :
    - div[role='article'] pour les blocs (stable)
    - time[datetime] pour la date (attribut sémantique)
    - div[dir='auto'] pour le texte (stable)
    - XPath sémantique pour l'auteur
    """
    print("  🚀 Extraction des commentaires...")
    commentaires = []
    seen = set()

    try:
        scroll_commentaires(container)

        # Chaque commentaire = un article imbriqué
        blocs = container.find_elements(By.CSS_SELECTOR, "div[role='article']")
        print(f"  📦 {len(blocs)} blocs détectés")

        if not blocs:
            print("  ❌ Aucun bloc de commentaire trouvé")
            return []

        for i, bloc in enumerate(blocs):
            try:
                # ── Auteur ────────────────────────────────────────────
                auteur = "Auteur inconnu"
                try:
                    auteur_el = bloc.find_element(
                        By.XPATH,
                        ".//a[contains(@href,'facebook.com/') and not(contains(@href,'comment_id'))]"
                        "//span[string-length(normalize-space(.)) > 0]"
                    )
                    auteur = auteur_el.text.strip()
                except Exception:
                    pass

                # ── Texte ─────────────────────────────────────────────
                texte = ""
                try:
                    text_els = bloc.find_elements(By.CSS_SELECTOR, "div[dir='auto']")
                    texte = " ".join(
                        el.text.strip() for el in text_els if el.text.strip()
                    ).strip()
                except Exception:
                    pass

                if not texte or len(texte) <= 1:
                    continue

                # Dédoublonnage
                key = f"{auteur}|{texte[:80]}"
                if key in seen:
                    continue
                seen.add(key)

                # ── Date ──────────────────────────────────────────────
                date_fmt = "Date inconnue"
                try:
                    # 1. Balise <time datetime=> — le plus fiable en 2026
                    time_el = bloc.find_element(By.CSS_SELECTOR, "time[datetime]")
                    raw = time_el.get_attribute("datetime") or time_el.text.strip()
                    date_fmt = convertir_date_facebook(raw)
                except Exception:
                    try:
                        # 2. Lien avec comment_id (texte relatif)
                        date_el = bloc.find_element(
                            By.XPATH, ".//a[contains(@href,'comment_id')]"
                        )
                        date_fmt = convertir_date_facebook(date_el.text.strip())
                    except Exception:
                        pass

                commentaires.append({
                    "date": date_fmt,
                    "auteur_com": auteur,
                    "source": "OLBCI",
                    "commentaire": texte,
                })

            except StaleElementReferenceException:
                print(f"  ⚠️ Bloc {i} périmé — ignoré")
            except Exception as e:
                print(f"  ⚠️ Erreur bloc {i}: {e}")

    except Exception as e:
        print(f"  ❌ Erreur extraction: {e}")

    print(f"  ✅ {len(commentaires)} commentaires extraits")
    return commentaires



def extraire_commentaires_depuis_articles(articles_list) -> list:
    """
    Extrait les commentaires depuis une liste d elements div[role='article']
    deja identifies comme commentaires (strategie A — DOM direct).
    Meme logique qu extraire_commentaires() mais sans container.
    """
    commentaires = []
    seen = set()

    for i, bloc in enumerate(articles_list):
        try:
            aria_label = bloc.get_attribute("aria-label") or ""

            # Auteur depuis aria-label
            auteur = "Auteur inconnu"
            try:
                m = re.search(
                    r"(?:Commentaire de|Reponse de|Comment by|Reply by|Réponse de)"
                    r"\s+(.+?)\s+(?:il y a|hace|ha|ago|\d)",
                    aria_label, re.IGNORECASE
                )
                if m:
                    auteur = m.group(1).strip()
                else:
                    a_el = bloc.find_element(
                        By.XPATH,
                        ".//a[contains(@href,'facebook.com/') "
                        "and not(contains(@href,'comment_id'))]"
                        "//span[string-length(normalize-space(.)) > 0]"
                    )
                    auteur = a_el.text.strip()
            except Exception:
                pass

            # Texte
            texte = ""
            try:
                text_els = bloc.find_elements(By.CSS_SELECTOR, "div[dir='auto']")
                texte = " ".join(
                    el.text.strip() for el in text_els if el.text.strip()
                ).strip()
            except Exception:
                pass

            if not texte or len(texte) <= 1:
                continue

            key = f"{auteur}|{texte[:80]}"
            if key in seen:
                continue
            seen.add(key)

            # Date
            date_fmt = "Date inconnue"
            try:
                time_el = bloc.find_element(By.CSS_SELECTOR, "time[datetime]")
                raw = time_el.get_attribute("datetime") or time_el.text.strip()
                date_fmt = convertir_date_facebook(raw)
            except Exception:
                try:
                    date_el = bloc.find_element(
                        By.XPATH, ".//a[contains(@href,'comment_id')]"
                    )
                    date_fmt = convertir_date_facebook(date_el.text.strip())
                except Exception:
                    m2 = re.search(r"il y a (.+)$|(\d+ \w+) ago",
                                   aria_label, re.IGNORECASE)
                    if m2:
                        date_fmt = convertir_date_facebook(
                            (m2.group(1) or m2.group(2)).strip()
                        )

            commentaires.append({
                "date":        date_fmt,
                "auteur_com":  auteur,
                "source":      "OLBCI",
                "commentaire": texte,
            })

        except StaleElementReferenceException:
            print(f"  ⚠️ Article {i} perime — ignore")
        except Exception as e:
            print(f"  ⚠️ Erreur article {i}: {e}")

    print(f"  ✅ {len(commentaires)} commentaires extraits (DOM direct)")
    return commentaires

def fermer_container():
    """Ferme le container de commentaires (bouton Fermer ou Échap)"""
    try:
        close_btns = driver.find_elements(
            By.XPATH,
            "//div[@role='button' and (@aria-label='Fermer' or @aria-label='Close')]"
        )
        for btn in close_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                human_delay(0.5, 1.0)
                print("  ✅ Container fermé")
                return
    except Exception:
        pass
    # Fallback : touche Échap
    try:
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        human_delay(0.5, 1.0)
    except Exception:
        pass


# ─────────────────────────────────────────────
# EXTRACTION GLOBALE — même logique que le scraper pages
# ─────────────────────────────────────────────
def extraire_commentaires_depuis_page_groupe() -> list:
    """
    Même logique que le scraper pages (doc 6) :
    Les commentaires sont déjà dans le DOM sous forme de
    div[role='article'] avec aria-label='Commentaire de X...'
    On les extrait tous en une seule passe globale sur toute la page,
    puis on les associe au post parent via le filtrage mot-clé.
    """
    print("\n🔍 Extraction globale des commentaires depuis le DOM...")
    data = []
    seen = set()

    comment_articles = driver.find_elements(
        By.XPATH,
        "//div[@role='article' and ("
        "contains(@aria-label,'Commentaire de') or "
        "contains(@aria-label,'commentaire de') or "
        "contains(@aria-label,'Réponse de') or "
        "contains(@aria-label,'réponse de') or "
        "contains(@aria-label,'Comment by') or "
        "contains(@aria-label,'comment by') or "
        "contains(@aria-label,'reply by') or "
        "contains(@aria-label,'Reply by')"
        ")]"
    )
    print(f"  📦 {len(comment_articles)} commentaires/réponses détectés sur la page")

    for i, block in enumerate(comment_articles):
        try:
            aria_label = block.get_attribute("aria-label") or ""

            # ── Auteur depuis aria-label ───────────────────────────────
            author_name = "Auteur inconnu"
            try:
                m = re.search(
                    r"(?:Commentaire de|Réponse de|Comment by|Reply by)\s+(.+?)\s+"
                    r"(?:il y a|hace|há|ago|\d)",
                    aria_label, re.IGNORECASE
                )
                if m:
                    author_name = m.group(1).strip()
                else:
                    a_el = block.find_element(
                        By.XPATH,
                        ".//a[contains(@href,'facebook.com/') "
                        "and not(contains(@href,'comment_id'))]"
                        "//span[string-length(normalize-space(.)) > 0]"
                    )
                    author_name = a_el.text.strip()
            except Exception:
                pass

            # ── Texte ─────────────────────────────────────────────────
            comment_text = ""
            try:
                text_els = block.find_elements(By.CSS_SELECTOR, "div[dir='auto']")
                comment_text = " ".join(
                    el.text.strip() for el in text_els if el.text.strip()
                ).strip()
            except Exception:
                pass

            if not comment_text or len(comment_text) <= 1:
                continue

            # ── Dédoublonnage ─────────────────────────────────────────
            key = f"{author_name}|{comment_text[:80]}"
            if key in seen:
                continue
            seen.add(key)

            # ── Texte du post parent (pour mot-clé et colonne "poste") ─
            texte_post = ""
            auteur_post = "Auteur inconnu"
            date_post = "Date inconnue"
            try:
                # Remonter au post parent : ancêtre article sans aria-label commentaire
                parent = block.find_element(
                    By.XPATH,
                    "ancestor::div[@role='article' and not("
                    "contains(@aria-label,'Commentaire de') or "
                    "contains(@aria-label,'commentaire de') or "
                    "contains(@aria-label,'Commentaires de') or "
                    "contains(@aria-label,'commentaires de') or "
                    "contains(@aria-label,'Réponse de') or "
                    "contains(@aria-label,'réponse de') or "
                    "contains(@aria-label,'Comment by') or "
                    "contains(@aria-label,'comment by') or "
                    "contains(@aria-label,'reply by') or "
                    "contains(@aria-label,'Reply by')"
                    ")][1]"
                )
                # Texte du post
                txt_els = parent.find_elements(By.CSS_SELECTOR,
                    "div[data-ad-comet-preview='message'], "
                    "div[data-ad-preview='message'], "
                    "div[dir='auto']"
                )
                texte_post = max(
                    (el.text.strip() for el in txt_els if el.text.strip()),
                    key=len, default=""
                )
                # Auteur du post
                for sel in ["h2 a span", "h3 a span", "strong a",
                            "a[role='link'] span[dir='auto']"]:
                    try:
                        el = parent.find_element(By.CSS_SELECTOR, sel)
                        nom = el.text.strip().split("·")[0].strip()
                        if nom and len(nom) > 2:
                            auteur_post = nom
                            break
                    except Exception:
                        continue
                # Date du post
                try:
                    te = parent.find_element(By.CSS_SELECTOR, "time[datetime]")
                    date_post = convertir_date_facebook(
                        te.get_attribute("datetime") or te.text.strip()
                    )
                except Exception:
                    pass
            except Exception:
                pass

            # ── Filtrage mot-clé sur le texte du post parent ───────────
            # On garde le commentaire si le post parent contient un mot-clé SGCI
            # OU si le commentaire lui-même contient un mot-clé
            if texte_post and not contient_mot_cle(texte_post):
                if not contient_mot_cle(comment_text):
                    continue

            # ── Date du commentaire ────────────────────────────────────
            formatted_date = "Date non trouvée"
            try:
                time_el = block.find_element(By.CSS_SELECTOR, "time[datetime]")
                raw_date = time_el.get_attribute("datetime") or time_el.text.strip()
                formatted_date = convertir_date_facebook(raw_date)
            except Exception:
                try:
                    date_el = block.find_element(
                        By.XPATH, ".//a[contains(@href,'comment_id')]"
                    )
                    formatted_date = convertir_date_facebook(date_el.text.strip())
                except Exception:
                    m2 = re.search(
                        r"il y a (.+)$|(\d+ \w+) ago", aria_label, re.IGNORECASE
                    )
                    if m2:
                        formatted_date = convertir_date_facebook(
                            (m2.group(1) or m2.group(2)).strip()
                        )

            data.append({
                "date":        formatted_date,
                "auteur_com":  author_name,
                "source":      "OLBCI",
                "commentaire": comment_text,
                "poste":       texte_post[:200],
                "date_post":   date_post,
                "auteur":      auteur_post,
            })

        except StaleElementReferenceException:
            print(f"  ⚠️ Bloc {i} périmé — ignoré")
        except Exception as e:
            print(f"  ⚠️ Erreur bloc {i} : {e}")

    print(f"  ✅ {len(data)} commentaires valides extraits")
    return data


def identifier_posts_groupe() -> list:
    """
    Dans un groupe Facebook, les div[role='article'] peuvent être :
      - des vrais posts du fil (aria-label absent ou generique)
      - des commentaires DEJA charges (aria-label='Commentaire de X...')
      - des reponses (aria-label='Reponse de X...')

    Cette fonction retourne UNIQUEMENT les vrais posts
    en excluant les articles dont l'aria-label indique un commentaire.
    """
    tous_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")

    posts_reels = []
    for art in tous_articles:
        lbl = (art.get_attribute("aria-label") or "").lower()
        # Exclure commentaires et reponses deja charges
        if any(kw in lbl for kw in [
            "commentaire de", "réponse de", "reponse de", "comment by", "comments by", "reply by",
            "réponses de", "commentaires de"
        ]):
            continue
        posts_reels.append(art)

    return posts_reels


# ─────────────────────────────────────────────
# ANALYSE DES POSTS
# ─────────────────────────────────────────────
def analyser_posts() -> list:
    """
    Analyse les vrais posts du groupe et extrait leurs commentaires.

    Deux strategies selon ce que le DOM contient :
      A) Commentaires DEJA dans le DOM sous le post (lazy-load Facebook)
         → extraction directe via aria-label='Commentaire de...'
      B) Commentaires masques derriere un clic
         → ouvrir_commentaires() + extraire_commentaires()
    """
    print("🔄 Analyse des posts...")
    tous_commentaires = []

    posts = identifier_posts_groupe()
    print(f"🔍 {len(posts)} vrais posts identifies (commentaires exclus)")

    posts_traites = set()   # eviter de retraiter le meme post

    for i in range(len(posts)):
        try:
            print(f"\n🧩 === POST {i+1}/{len(posts)} ===")

            # Recharger pour eviter StaleElement
            posts = identifier_posts_groupe()
            if i >= len(posts):
                break
            post = posts[i]

            # Cle unique pour ce post (href du lien permalink)
            try:
                post_key = post.find_element(
                    By.XPATH,
                    ".//a[contains(@href,'/posts/') or contains(@href,'/permalink/')]"
                ).get_attribute("href") or str(i)
            except Exception:
                post_key = str(i)

            if post_key in posts_traites:
                print("  ⏭️ Post deja traite — ignore")
                continue
            posts_traites.add(post_key)

            # Cliquer sur "Voir plus" si present
            cliquer_voir_plus(post)

            # Texte du post
            texte_post = extraire_texte_post(post)
            if not texte_post:
                print("  ⛔ Texte introuvable — post ignore")
                continue

            # Auteur & date
            date_post, auteur_post = extraire_auteur_date(post)

            # Verification mot-cle
            mot_cle_texte = contient_mot_cle(texte_post)
            mot_cle_image = False
            if not mot_cle_texte:
                mot_cle_image = analyser_images_post(post)

            if not mot_cle_texte and not mot_cle_image:
                print("  ⛔ Aucun mot-cle — post ignore")
                continue

            print("  ✅ Mot-cle detecte ! Extraction des commentaires...")

            # ── Strategie A : commentaires deja dans le DOM ──────────────
            coms_dom = post.find_elements(
                By.XPATH,
                ".//div[@role='article' and ("
                "contains(@aria-label,'Commentaire de') or "
                "contains(@aria-label,'Commentaires de') or "
                "contains(@aria-label,'commentaires de') or "
                "contains(@aria-label,'commentaire de') or "
                "contains(@aria-label,'Réponse de') or "
                "contains(@aria-label,'réponse de') or "
                "contains(@aria-label,'Comment by') or "
                "contains(@aria-label,'comment by') or "
                "contains(@aria-label,'reply by') or "
                "contains(@aria-label,'Reply by')"
                ")]"
            )

            if coms_dom:
                print(f"  📥 Strategie A : {len(coms_dom)} commentaires deja dans le DOM")
                commentaires = extraire_commentaires_depuis_articles(coms_dom)
            else:
                # ── Strategie B : clic pour ouvrir le panneau ────────────
                print("  🖱️ Strategie B : ouverture du panneau commentaires")
                if not ouvrir_commentaires(post):
                    continue
                container = trouver_container_commentaires()
                if not container:
                    fermer_container()
                    continue
                commentaires = extraire_commentaires(container)
                fermer_container()

            # Enrichissement avec les infos du post
            for com in commentaires:
                com["poste"]     = texte_post[:200]
                com["date_post"] = date_post
                com["auteur"]    = auteur_post

            tous_commentaires.extend(commentaires)
            human_delay(1.5, 3.0)

        except StaleElementReferenceException:
            print(f"  ⚠️ Post {i} perime — on continue")
        except Exception as e:
            print(f"  ⚠️ Erreur post {i}: {e}")

    return tous_commentaires


def scroll_et_charger() -> list:
    """
    Même logique que scroll_page_and_load_content() du scraper pages :
    - scroll progressif pour activer le lazy-load
    - extraction globale en une seule passe sur tout le DOM
    - pas de boucle post par post
    """
    print("🔄 Scroll et chargement du fil de groupe...")

    prev_count = 0
    for i in range(MAX_SCROLL_ATTEMPTS):
        print(f"\n📜 === SCROLL {i+1}/{MAX_SCROLL_ATTEMPTS} ===")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_delay(SCROLL_WAIT_TIME, SCROLL_WAIT_TIME + 2)

        # Cliquer sur "Afficher plus de commentaires" si présent
        try:
            more_btns = driver.find_elements(
                By.XPATH,
                "//div[@role='button' and ("
                "contains(., 'Afficher plus de commentaires') or "
                "contains(., 'Voir plus de commentaires') or "
                "contains(., 'View more comments')"
                ")]"
            )
            for mb in more_btns:
                if mb.is_displayed():
                    driver.execute_script("arguments[0].click();", mb)
                    print("    📥 'Afficher plus' cliqué")
                    human_delay(2, 3)
        except Exception:
            pass

        # Compter les commentaires pour détecter la stabilité
        current_count = len(driver.find_elements(
            By.XPATH,
            "//div[@role='article' and ("
            "contains(@aria-label,'Commentaire de') or "
            "contains(@aria-label,'commentaire de') or "
            "contains(@aria-label,'Commentaires de') or "
            "contains(@aria-label,'commentaires de') or "
            "contains(@aria-label,'Réponse de') or "
            "contains(@aria-label,'réponse de') or "
            "contains(@aria-label,'Comment by') or "
            "contains(@aria-label,'comment by') or "
            "contains(@aria-label,'reply by') or "
            "contains(@aria-label,'Reply by')"
            ")]"
        ))
        print(f"    💬 {current_count} commentaires visibles dans le DOM")
        if current_count == prev_count and i > 0:
            print("    ℹ️ Stable — scroll arrêté")
            break
        prev_count = current_count

    # Extraction globale en une seule passe
    return extraire_commentaires_depuis_page_groupe()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("🚀 Démarrage du scraper Facebook Groupe (mise à jour mars 2026)\n")

    try:
        # 1. Cookies
        if not load_cookies():
            print("❌ Impossible de charger les cookies — abandon")
            return

        # 2. Accès au groupe
        print(f"🔗 Accès au groupe : {GROUP_URL}")
        driver.get(GROUP_URL)
        human_delay(4, 6)

        # 3. Vérification connexion
        if not verify_login():
            print("❌ Session expirée — rechargement nécessaire")
            driver.get("https://www.facebook.com/")
            human_delay(3, 5)
            if not verify_login():
                print("❌ Toujours déconnecté — abandon")
                return
        print("✅ Connexion vérifiée")

        # 4. Chargement de la page
        wait_for_page_load()
        human_delay(8, 12)  # Laisser le fil du groupe se stabiliser

        # 5. Scroll & extraction
        commentaires = scroll_et_charger()

        if not commentaires:
            print("❌ Aucun commentaire extrait")
            return

        # 6. Sauvegarde
        df_new = pd.DataFrame(commentaires)
        df_new = df_new.drop_duplicates(subset=["auteur_com", "commentaire"])

        if not data_existante.empty:
            df_final = (
                pd.concat([data_existante, df_new], ignore_index=True)
                .drop_duplicates(subset=["auteur_com", "commentaire"])
            )
        else:
            df_final = df_new

        df_final.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

        print(f"\n✅ Extraction terminée !")
        print(f"📁 Fichier : {OUTPUT_FILE}")
        print(f"📊 Nouvelles lignes : {len(df_new)} | Total : {len(df_final)}")

        # Aperçu
        print("\n📝 Aperçu (3 premiers commentaires) :")
        for i, com in enumerate(commentaires[:3]):
            print(f"  {i+1}. [{com.get('auteur_com','?')}] {com['commentaire'][:80]}...")

    except KeyboardInterrupt:
        print("\n⚠️ Arrêt demandé par l'utilisateur")
    except Exception as e:
        print(f"❌ Erreur fatale : {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🔚 Fermeture du navigateur...")
        driver.quit()


if __name__ == "__main__":
    main()