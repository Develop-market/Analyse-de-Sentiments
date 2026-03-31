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
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
URLS = [
    "https://www.facebook.com/sibciv",
    "https://web.facebook.com/ecobankciv",
    "https://web.facebook.com/NSIABANQUECI",
    "https://web.facebook.com/BNI.Cotedivoire",
    "https://web.facebook.com/societegenerale.cotedivoire",
    "https://www.facebook.com/BanqueAtlantiqueCI",
]

SOURCES = [
    "page_SIB",
    "page_ecobank",
    "page_NSIA",
    "page_BNI",
    "page_sgci",
    "page_BACI",
]

MAX_SCROLL_ATTEMPTS = 3          # Augmenté pour charger plus de posts
SCROLL_WAIT_TIME = 4             # Réduit — plus réaliste
COMMENT_LOAD_WAIT = 3
OUTPUT_FILE = "facebook_commentaires_concatene.csv"


# Délais aléatoires pour simuler un comportement humain (anti-détection 2026)
def human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))


options = EdgeOptions()
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-infobars")
options.add_argument("--lang=fr-FR")
# User-agent réaliste (mis à jour mars 2026)
options.add_argument(
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"
)
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver_path = "./edgedriver_win64/msedgedriver.exe"
driver = webdriver.Edge(service=EdgeService(executable_path=driver_path),options=options)

# Masquer la propriété webdriver (anti-détection 2026)
driver.execute_cdp_cmd(
    "Page.addScriptToEvaluateOnNewDocument",
    {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
)


# ─────────────────────────────────────────────
# Authentification par cookies
# ─────────────────────────────────────────────
def load_cookies():
    """Charger et injecter les cookies Facebook"""
    try:
        driver.get("https://www.facebook.com/")
        time.sleep(3)

        with open("facebook_cookies.json", "r", encoding="utf-8") as file:
            cookies = json.load(file)

        print(f"📁 {len(cookies)} cookies chargés")

        for cookie in cookies:
            # Nettoyer les attributs non supportés par Selenium
            for key in ["sameSite", "storeId", "id", "hostOnly", "session", "expirationDate"]:
                cookie.pop(key, None)
            # Correction du domaine pour compatibilité 2026
            if "domain" in cookie and not cookie["domain"].startswith("."):
                cookie["domain"] = "." + cookie["domain"].lstrip(".")
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"⚠️ Cookie ignoré ({cookie.get('name', '?')}): {e}")

        print("✅ Cookies injectés")
        return True

    except FileNotFoundError:
        print("❌ Fichier facebook_cookies.json introuvable !")
        return False
    except Exception as e:
        print(f"❌ Erreur cookies : {e}")
        return False


def verify_login():
    """Vérifier que la session est active"""
    try:
        # Indicateurs de non-connexion (labels en français et anglais)
        login_indicators = [
            "//input[@name='email']",
            "//input[@name='pass']",
        ]
        for indicator in login_indicators:
            if driver.find_elements(By.XPATH, indicator):
                return False
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# Chargement de la page
# ─────────────────────────────────────────────
def wait_for_facebook_page_loaded(timeout=60):
    """Attendre que la page Facebook soit prête"""
    print("🔄 Chargement de la page...")

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        print("⚠️ Timeout readyState")

    # ── Sélecteurs robustes 2026 : role= et data-* sont stables ──
    stable_selectors = [
        "div[role='main']",
        "div[role='article']",
        "div[data-pagelet='ProfileTimeline']",
        "div[data-pagelet='PageTimeline']",
    ]

    for sel in stable_selectors:
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            print(f"✅ Page prête ({sel})")
            return True
        except TimeoutException:
            continue

    print("⚠️ Aucun sélecteur principal trouvé — on continue quand même")
    human_delay(2, 4)
    return True


# ─────────────────────────────────────────────
# Scroll de la page principale
# ─────────────────────────────────────────────
def scroll_page_and_load_content():
    """
    Scroll pour charger les posts ET leurs commentaires.
    Diagnostic confirmé : sur les pages publiques Facebook (2026),
    les commentaires sont DEJA dans le DOM sous chaque post.
    Aucun clic sur un bouton n est necessaire.
    """
    print(f"🔄 Scroll ({MAX_SCROLL_ATTEMPTS} passes)...")

    prev_count = 0
    for i in range(MAX_SCROLL_ATTEMPTS):
        print(f"  📜 Scroll {i + 1}/{MAX_SCROLL_ATTEMPTS}")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_delay(SCROLL_WAIT_TIME, SCROLL_WAIT_TIME + 2)

        # Cliquer sur "Afficher plus de commentaires" si present
        try:
            more_btns = driver.find_elements(
                By.XPATH,
                "//div[@role='button' and ("
                "contains(., 'Voir plus de commentaires') or "
                "contains(., 'Afficher plus de commentaires') or "
                "contains(., 'Voir 1 réponse') or "
                "contains(., 'Voir les x réponses') or "
                "contains(., 'View more comments') or "
                "contains(., 'commentaires supplementaires')"
                ")]"
            )
            for mb in more_btns:
                if mb.is_displayed():
                    driver.execute_script("arguments[0].click();", mb)
                    print("    📥 'Afficher plus de commentaires' clique")
                    human_delay(2, 3)
        except Exception:
            pass

        # Compter les commentaires visibles
        current_count = len(driver.find_elements(
            By.XPATH,
            "//div[@role='article' and ("
            "contains(@aria-label,'Commentaire de') or "
            "contains(@aria-label,'Reponse de') or "
            "contains(@aria-label,'Comment by') or "
            "contains(@aria-label,'Reply by')"
            ")]"
        ))
        print(f"    💬 {current_count} commentaires visibles")
        if current_count == prev_count and i > 0:
            print("    ℹ️ Aucun nouveau commentaire — scroll arrete")
            break
        prev_count = current_count

    print("✅ Scroll termine")
    return extraire_commentaires_depuis_page()


# ─────────────────────────────────────────────
# Extraction directe des commentaires depuis la page
# ─────────────────────────────────────────────
def extraire_commentaires_depuis_page() -> list:
    """
    Diagnostic mars 2026 : les commentaires sont DEJA dans le DOM
    sous forme de div[role='article'] avec aria-label=
    'Commentaire de X il y a Y' ou 'Reponse de X au commentaire de Y'.

    On les extrait directement sans cliquer sur aucun bouton.
    """
    print("\n🔍 Extraction directe des commentaires depuis le DOM...")
    data = []
    seen = set()

    # Selectionner uniquement les vrais commentaires/reponses
    # (exclure les articles qui sont des posts de la page)
    comment_articles = driver.find_elements(
        By.XPATH,
        "//div[@role='article' and ("
        "contains(@aria-label,'Commentaire de') or "
        "contains(@aria-label,'Réponse de') or "
        "contains(@aria-label,'Comment by') or "
        "contains(@aria-label,'Reply by')"
        ")]"
    )
    print(f"  📦 {len(comment_articles)} commentaires/réponses détectés")

    for i, block in enumerate(comment_articles):
        try:
            aria_label = block.get_attribute("aria-label") or ""

            # ── Auteur depuis aria-label ───────────────────────────────
            # Format : "Commentaire de PRENOM NOM il y a X semaines"
            author_name = "Auteur inconnu"
            try:
                # Extraire le nom entre "de " et " il y a" / " il y a" / " há"
                m = re.search(
                    r"(?:Commentaire de|Réponse de|Comment by|Reply by)\s+(.+?)\s+"
                    r"(?:il y a|hace|há|ago|\d)",
                    aria_label, re.IGNORECASE
                )
                if m:
                    author_name = m.group(1).strip()
                else:
                    # Fallback : lien profil dans le bloc
                    a_el = block.find_element(
                        By.XPATH,
                        ".//a[contains(@href,'facebook.com/') "
                        "and not(contains(@href,'comment_id'))]"
                        "//span[string-length(normalize-space(.)) > 0]"
                    )
                    author_name = a_el.text.strip()
            except Exception:
                pass

            # ── Texte du commentaire ───────────────────────────────────
            comment_text = ""
            try:
                text_els = block.find_elements(By.CSS_SELECTOR, "div[dir='auto']")
                comment_text = " ".join(
                    el.text.strip() for el in text_els if el.text.strip()
                ).strip()
            except Exception:
                pass

            # Filtrer les blocs vides ou trop courts
            if not comment_text or len(comment_text) <= 1:
                continue

            # ── Dédoublonnage ─────────────────────────────────────────
            key = f"{author_name}|{comment_text[:80]}"
            if key in seen:
                continue
            seen.add(key)

            # ── Date ──────────────────────────────────────────────────
            formatted_date = "Date non trouvée"
            try:
                # 1. Balise <time datetime=> — le plus fiable
                time_el = block.find_element(By.CSS_SELECTOR, "time[datetime]")
                raw_date = time_el.get_attribute("datetime") or time_el.text.strip()
                formatted_date = convertir_date_facebook(raw_date)
            except Exception:
                try:
                    # 2. Lien avec comment_id (texte relatif ex: "2 sem.")
                    date_el = block.find_element(
                        By.XPATH, ".//a[contains(@href,'comment_id')]"
                    )
                    formatted_date = convertir_date_facebook(date_el.text.strip())
                except Exception:
                    # 3. Extraire depuis aria-label "il y a 2 semaines"
                    m = re.search(
                        r"il y a (.+)$|(\d+ \w+) ago", aria_label, re.IGNORECASE
                    )
                    if m:
                        formatted_date = convertir_date_facebook(
                            (m.group(1) or m.group(2)).strip()
                        )

            data.append({
                "date":        formatted_date,
                "auteur":      author_name,
                "source":      "",   # rempli dans main()
                "commentaire": comment_text,
            })

        except StaleElementReferenceException:
            print(f"  ⚠️ Bloc {i} périmé — ignoré")
        except Exception as e:
            print(f"  ⚠️ Erreur bloc {i} : {e}")

    print(f"  ✅ {len(data)} commentaires valides extraits")
    return data


# ─────────────────────────────────────────────
# Trouver le panneau de commentaires
# ─────────────────────────────────────────────
def find_comment_container():
    """
    Sélecteurs robustes 2026 : on évite les classes hachées et on cible
    des attributs sémantiques stables.
    """
    CONTAINER_SELECTORS = [
        # Dialogue / popover de commentaires
        "div[role='dialog']",
        # Section commentaires dans l'article courant (attribut data stable)
        "div[data-visualcompletion='ignore-dynamic']",
        # Fallback : liste de commentaires (role=list dans un article)
        "ul[data-visualcompletion='ignore-dynamic']",
        # Dernier recours : article imbriqué contenant d'autres articles
        "div[role='main'] div[role='article'] div[role='article']",
    ]

    for sel in CONTAINER_SELECTORS:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            container = driver.find_element(By.CSS_SELECTOR, sel)
            print(f"  ✅ Container trouvé : {sel}")
            return container
        except (TimeoutException, NoSuchElementException):
            continue

    return None


# ─────────────────────────────────────────────
# Scroll dans le container de commentaires
# ─────────────────────────────────────────────
def scroll_comment_container(container):
    """Défiler le container jusqu'à stabilité pour charger tous les commentaires"""
    print("  🔄 Scroll des commentaires...")
    prev_count = 0
    stale_rounds = 0

    for _ in range(15):  # max 15 passes
        try:
            items = container.find_elements(By.CSS_SELECTOR, "div[role='article']")
            current_count = len(items)
        except StaleElementReferenceException:
            print("  ⚠️ Container périmé — arrêt du scroll")
            break

        if current_count == prev_count:
            stale_rounds += 1
            if stale_rounds >= 2:
                break
        else:
            stale_rounds = 0
            prev_count = current_count
            print(f"    📊 {current_count} commentaires visibles")

        try:
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;", container
            )
        except Exception:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        human_delay(COMMENT_LOAD_WAIT - 0.5, COMMENT_LOAD_WAIT + 0.5)

        # Cliquer sur "Afficher plus de commentaires" si disponible
        try:
            more_btns = driver.find_elements(
                By.XPATH,
                "//div[@role='button' and ("
                "contains(., 'Afficher plus') or "
                "contains(., 'View more') or "
                "contains(., 'plus de commentaires')"
                ")]"
            )
            for mb in more_btns:
                if mb.is_displayed():
                    driver.execute_script("arguments[0].click();", mb)
                    human_delay(1.5, 2.5)
                    break
        except Exception:
            pass

    print(f"  ✅ Scroll terminé — {prev_count} commentaires visibles")


# ─────────────────────────────────────────────
# Conversion des dates relatives Facebook
# ─────────────────────────────────────────────
def convertir_date_facebook(date_str: str) -> str:
    """Convertit une date relative Facebook (FR/EN) en JJ-MM-AAAA"""
    aujourd_hui = datetime.today()
    s = date_str.lower().strip()

    try:
        # Minutes
        if re.search(r"\d+\s*m(in)?", s):
            minutes = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(minutes=minutes)).strftime("%d-%m-%Y")

        # Heures (h / hr / hour)
        if re.search(r"\d+\s*(h|hr|hour)", s):
            heures = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(hours=heures)).strftime("%d-%m-%Y")

        # Jours (j / d / day)
        if re.search(r"\d+\s*(j|d|day)", s):
            jours = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(days=jours)).strftime("%d-%m-%Y")

        # Semaines (sem / w / week)
        if re.search(r"\d+\s*(sem|w|week)", s):
            semaines = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(weeks=semaines)).strftime("%d-%m-%Y")

        # Mois (mois / mo / month)
        if re.search(r"\d+\s*(mois|mo|month)", s):
            mois = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(days=mois * 30)).strftime("%d-%m-%Y")

        # Ans (an / ans / y / year)
        if re.search(r"\d+\s*(an|ans|y|year)", s):
            ans = int(re.search(r"(\d+)", s).group(1))
            return (aujourd_hui - timedelta(days=ans * 365)).strftime("%d-%m-%Y")

        # "hier" / "yesterday"
        if "hier" in s or "yesterday" in s:
            return (aujourd_hui - timedelta(days=1)).strftime("%d-%m-%Y")

        # "aujourd" / "today" / "just now" / "à l'instant"
        if any(k in s for k in ["aujourd", "today", "just now", "instant"]):
            return aujourd_hui.strftime("%d-%m-%Y")

        # Date absolue : "10 mai", "10 May", "10 mai 2024"
        for fmt in ("%d %b %Y", "%d %B %Y", "%d %b", "%d %B"):
            try:
                d = datetime.strptime(
                    date_str.strip() + (f" {aujourd_hui.year}" if len(fmt.split()) == 2 else ""),
                    fmt if "Y" in fmt else fmt + " %Y"
                )
                return d.strftime("%d-%m-%Y")
            except ValueError:
                continue

        # Timestamp ISO 8601 (attribut datetime= des balises <time>)
        if "t" in s or "-" in s:
            for iso_fmt in ("%Y-%m-%dT%H:%M:%S+%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(date_str[:19], iso_fmt[:len(date_str[:19])]).strftime("%d-%m-%Y")
                except ValueError:
                    continue

        return "Format inconnu"

    except Exception:
        return "Erreur de conversion"


# ─────────────────────────────────────────────
# Extraction des commentaires
# ─────────────────────────────────────────────
def extract_comments(container) -> list:
    """
    Extraction robuste 2026 :
    - Utilise div[role='article'] pour cibler chaque commentaire
    - Lit l'attribut datetime= de la balise <time> pour la date (stable)
    - Utilise des XPath sémantiques pour auteur et texte
    """
    print("  🚀 Extraction des commentaires...")
    scroll_comment_container(container)

    data = []
    seen_texts = set()

    try:
        # Chaque commentaire est un article imbriqué
        comment_blocks = container.find_elements(By.CSS_SELECTOR, "div[role='article']")
        print(f"  📦 {len(comment_blocks)} blocs détectés")

        for i, block in enumerate(comment_blocks):
            try:
                # ── Auteur ────────────────────────────────────────────────
                author_name = "Auteur inconnu"
                try:
                    # Lien de profil contenant le nom (XPath sémantique)
                    author_el = block.find_element(
                        By.XPATH,
                        ".//a[contains(@href, 'facebook.com/') and not(contains(@href,'comment_id'))]"
                        "//span[string-length(normalize-space(.)) > 0]"
                    )
                    author_name = author_el.text.strip()
                except Exception:
                    pass

                # ── Texte du commentaire ──────────────────────────────────
                comment_text = ""
                try:
                    # div[dir='auto'] contient systématiquement le texte en 2026
                    text_els = block.find_elements(By.CSS_SELECTOR, "div[dir='auto']")
                    comment_text = " ".join(
                        el.text.strip() for el in text_els if el.text.strip()
                    ).strip()
                except Exception:
                    pass

                if not comment_text or len(comment_text) <= 1:
                    continue

                # Dédoublonnage
                key = f"{author_name}|{comment_text[:80]}"
                if key in seen_texts:
                    continue
                seen_texts.add(key)

                # ── Date ──────────────────────────────────────────────────
                formatted_date = "Date non trouvée"
                try:
                    # 1. Balise <time> avec attribut datetime= (le plus fiable)
                    time_el = block.find_element(By.CSS_SELECTOR, "time[datetime]")
                    raw_date = time_el.get_attribute("datetime") or time_el.text.strip()
                    formatted_date = convertir_date_facebook(raw_date)
                except Exception:
                    try:
                        # 2. Lien contenant comment_id (texte relatif)
                        date_el = block.find_element(
                            By.XPATH,
                            ".//a[contains(@href,'comment_id')]"
                        )
                        formatted_date = convertir_date_facebook(date_el.text.strip())
                    except Exception:
                        pass

                data.append({
                    "date": formatted_date,
                    "auteur": author_name,
                    "source": "",       # sera rempli dans main()
                    "commentaire": comment_text,
                })

            except StaleElementReferenceException:
                print(f"  ⚠️ Bloc {i} périmé — ignoré")
            except Exception as e:
                print(f"  ⚠️ Erreur bloc {i} : {e}")

    except Exception as e:
        print(f"  ❌ Erreur générale extraction : {e}")

    print(f"  ✅ {len(data)} commentaires valides extraits")
    return data


# ─────────────────────────────────────────────
# Point d'entrée principal
# ─────────────────────────────────────────────
def main():
    print("🚀 Démarrage du scraper Facebook (mise à jour mars 2026)...")

    # Charger le CSV existant si présent
    try:
        existing_data = pd.read_csv(OUTPUT_FILE)
        print(f"📂 {len(existing_data)} lignes existantes chargées depuis {OUTPUT_FILE}")
    except FileNotFoundError:
        existing_data = pd.DataFrame(columns=["date", "auteur", "source", "commentaire"])
        print("📂 Nouveau fichier CSV créé")

    try:
        if not load_cookies():
            print("❌ Impossible de charger les cookies — abandon")
            return

        all_data = []

        for url, source in zip(URLS, SOURCES):
            print(f"\n{'─'*60}")
            print(f"🔗 Source : {source}  ({url})")
            print(f"{'─'*60}")

            driver.get(url)
            human_delay(4, 6)

            if not verify_login():
                print("❌ Session expirée — rechargement des cookies nécessaire")
                # Tentative de re-navigation
                driver.get("https://www.facebook.com/")
                human_delay(3, 5)
                if not verify_login():
                    print("❌ Toujours déconnecté — abandon")
                    return

            wait_for_facebook_page_loaded()
            comments_data = scroll_page_and_load_content()

            if not comments_data:
                print(f"⚠️ Aucun commentaire extrait pour {source}")
                continue

            for c in comments_data:
                c["source"] = source

            all_data.extend(comments_data)
            print(f"✅ {len(comments_data)} commentaires récupérés depuis {source}")
            human_delay(3, 6)   # Pause entre les pages (anti-ban)

        # ── Sauvegarde ────────────────────────────────────────────────
        if not all_data:
            print("\n❌ Aucun commentaire extrait — CSV non modifié")
            return

        df_new = pd.DataFrame(all_data)
        df_final = (
            pd.concat([existing_data, df_new], ignore_index=True)
            .drop_duplicates(subset=["auteur", "commentaire", "source"])
        )
        df_final.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

        print(f"\n✅ Extraction terminée")
        print(f"📁 Fichier : {OUTPUT_FILE}")
        print(f"📊 Nouvelles lignes : {len(df_new)} | Total : {len(df_final)}")

    except KeyboardInterrupt:
        print("\n⚠️ Arrêt demandé")
    except Exception as e:
        print(f"\n❌ Erreur fatale : {e}")
    finally:
        print("🔚 Fermeture du navigateur...")
        driver.quit()


if __name__ == "__main__":
    main()
