import time
import json
import re
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configuration
#GROUP_URL = "https://web.facebook.com/societegenerale.cotedivoire"
URLS = [
    "https://www.facebook.com/sibciv",
     "https://web.facebook.com/ecobankciv",
     "https://web.facebook.com/NSIABANQUECI",
     "https://web.facebook.com/BNI.Cotedivoire",
     "https://web.facebook.com/societegenerale.cotedivoire",
     "https://www.facebook.com/BanqueAtlantiqueCI"
     


]

SOURCES = [
    "page_SIB",
    "page_ecobank",
    "page_NSIA",
    "page_BNI",
    "page_sgci",
    "page_BACI"
]


data = pd.read_csv("facebook_commentaires_concatene.csv")

MAX_SCROLL_ATTEMPTS = 1
SCROLL_WAIT_TIME = 10 
COMMENT_LOAD_WAIT = 4

index  = 0
# Initialisation du navigateur Edge
options = EdgeOptions()
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
driver_path = "./edgedriver_win64/msedgedriver.exe"  # ← ← ton chemin exact ici
driver = webdriver.Edge(service=EdgeService(executable_path=driver_path), options=options)

def load_cookies():
    """Charger et injecter les cookies Facebook"""
    try:
        driver.get("https://web.facebook.com/sibciv")
        time.sleep(3)
        
        with open("facebook_cookies.json", "r", encoding="utf-8") as file:
            cookies = json.load(file)
        
        print(f"📁 {len(cookies)} cookies chargés depuis le fichier")
        
        for cookie in cookies:
            # Nettoyer les attributs non supportés
            for key in ["sameSite", "storeId", "id", "hostOnly", "session"]:
                cookie.pop(key, None)
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"⚠️ Erreur avec le cookie {cookie.get('name', 'inconnu')}: {e}")
        
        print("✅ Cookies injectés avec succès")
        return True
        
    except FileNotFoundError:
        print("❌ Fichier facebook_cookies.json non trouvé!")
        return False
    except Exception as e:
        print(f"❌ Erreur lors du chargement des cookies: {e}")
        return False

def verify_login():
    """Vérifier si l'utilisateur est connecté"""
    try:
        # Chercher des éléments indiquant qu'on n'est pas connecté
        login_indicators = [
            "//input[@name='email']",
            "//input[@name='pass']",
            "//a[contains(text(), 'Se connecter')]",
            "//button[contains(text(), 'Se connecter')]"
        ]
        
        for indicator in login_indicators:
            if driver.find_elements(By.XPATH, indicator):
                return False
        
        return True
        
    except Exception as e:
        print(f"⚠️ Erreur lors de la vérification de connexion: {e}")
        return False

def wait_for_facebook_page_loaded(timeout=60):
    """Attendre que la page Facebook soit complètement chargée"""
    print("🔄 Attente du chargement de la page Facebook...")
    
    # 1. Attendre que le document soit prêt
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        print("✅ Document ready")
    except TimeoutException:
        print("⚠️ Timeout document ready")
    
    # 2. Attendre les éléments principaux Facebook
    main_selectors = [
        "[role='main']",
        "[data-pagelet]",
        "div[id^='mount_']",
        "div[data-ad-comet-preview='message']",
        "div[role='article']"
    ]
    
    element_found = False
    for selector in main_selectors:
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            print(f"✅ Élément principal trouvé: {selector}")
            element_found = True
            break
        except TimeoutException:
            continue
    
    if not element_found:
        print("⚠️ Aucun élément principal trouvé, continuons...")
    
    # 3. Attendre que les spinners/loaders disparaissent
    loader_selectors = [
        "[aria-label='Chargement...']",
        ".loading",
        ".spinner",
        "[role='progressbar']"
    ]
    
    for selector in loader_selectors:
        try:
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, selector))
            )
            print(f"✅ Loader disparu: {selector}")
        except TimeoutException:
            continue
    
    # 4. Attendre stabilité du contenu
    try:
        wait_for_content_stability(
            selector="div[data-ad-comet-preview='message'], div[role='article']",
            timeout=20,
            stable_time=3
        )
    except Exception as e:
        print(f"⚠️ Erreur stabilité: {e}")
    
    print("✅ Page Facebook chargée!")
    return True

def wait_for_content_stability(selector, timeout=30, stable_time=3):
    """Attendre que le contenu soit stable"""
    print(f"🔄 Attente de stabilité du contenu: {selector}")
    
    start_time = time.time()
    last_count = 0
    stable_start = None
    
    while time.time() - start_time < timeout:
        try:
            current_count = len(driver.find_elements(By.CSS_SELECTOR, selector))
            
            if current_count == last_count:
                if stable_start is None:
                    stable_start = time.time()
                elif time.time() - stable_start >= stable_time:
                    print(f"✅ Contenu stable: {current_count} éléments")
                    return True
            else:
                stable_start = None
                last_count = current_count
                print(f"📊 Éléments détectés: {current_count}")
            
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Erreur vérification stabilité: {e}")
            time.sleep(1)
    
    print(f"⚠️ Timeout stabilité après {timeout}s")
    return False

def scroll_page_and_load_content():
    """Faire défiler la page pour charger plus de contenu"""
    print("🔄 Scroll de la page pour charger le contenu...")
    
    for i in range(MAX_SCROLL_ATTEMPTS):
        print(f"📜 Scroll {i+1}/{MAX_SCROLL_ATTEMPTS}")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_WAIT_TIME)
    
    print("✅ Scroll terminé")

    # Récupération des commentaires de tous les posts visibles
    data = click_comment_buttons()
    return data


def click_comment_buttons():
    """Cliquer sur tous les boutons de commentaires"""
    print("🔄 Recherche et clic sur les boutons de commentaires...")

    comment_button_selectors = [
        "div[id^='_r_'][role='button']",
    ]

    buttons_clicked = 0
    comments_data = []

    for selector in comment_button_selectors:
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, selector)
            print(f"🔍 Trouvé {len(buttons)} boutons avec le sélecteur: {selector}")

            for i, btn in enumerate(buttons):
                try:
                    print(f"➡️ Traitement du bouton {i+1}/{len(buttons)}")
                    if btn.is_displayed() and btn.is_enabled():
                        driver.execute_script("arguments[0].click();", btn)
                        buttons_clicked += 1
                        time.sleep(2)

                        container = find_comment_container()
                        if not container:
                            print("❌ Aucun container de commentaires trouvé pour ce bouton")
                            continue  # Ne retourne plus, passe juste au bouton suivant

                        # Extraction des commentaires
                        comments = extract_comments(container)
                        print(f"💬 {len(comments)} commentaires extraits")
                        comments_data.extend(comments)

                        # Tentative de fermeture du container
                        close_buttons = driver.find_elements(By.CSS_SELECTOR, "div[aria-label='Fermer']")
                        for c in close_buttons:
                            try:
                                if c.is_displayed():
                                    driver.execute_script("arguments[0].click();", c)
                                    time.sleep(1)
                                    print("✅ Container de commentaires fermé")
                            except Exception:
                                continue
                except Exception as e:
                    print(f"⚠️ Erreur lors du clic ou de l'extraction : {e}")
                    continue

        except Exception as e:
            print(f"⚠️ Erreur avec le sélecteur {selector}: {e}")

    print(f"✅ {buttons_clicked} boutons de commentaires cliqués")
    return comments_data

    

def find_comment_container():
    """Trouver le container de commentaires avec différents sélecteurs"""
    print("🔍 Recherche du container de commentaires...")
    
    container_selectors = [
        "div.html-div.x14z9mp.xat24cr.x1lziwak.xexx8yu.xyri2b.x18d9i69.x1c1uobl.x1gslohp",
    ]
    
    for selector in container_selectors:
        try:
            container = driver.find_element(By.CSS_SELECTOR, selector)
            print(f"✅ Container trouvé avec: {selector}")
            return container
        except NoSuchElementException:
            print(f"⏳ Sélecteur non trouvé: {selector}")
            continue
    
    print("❌ Aucun container de commentaires trouvé")
    return None

def scroll_comment_container(container):
    """Faire défiler le container de commentaires jusqu'à stabilité"""
    print("🔄 Scroll du container de commentaires...")
    
    previous_children_count = 0

    
    while True:
        # Compter les enfants actuels
        current_children_count = len(container.find_elements(By.XPATH, "./*"))
        
        # Si le nombre d'enfants n'a pas changé, on sort
        if current_children_count == previous_children_count:
            print(f"✅ Scroll terminé. Nombre final d'enfants: {current_children_count}")
            break
        
        previous_children_count = current_children_count
        print(f"📊 Enfants trouvés: {current_children_count}")
        
        # Scroll vers le bas du container
        driver.execute_script("""
            var container = arguments[0];
            if (container.lastElementChild) {
                container.lastElementChild.scrollIntoView({ 
                    behavior: 'instant', 
                    block: 'end' 
                });
            }
        """, container)
        
        # Attendre que les nouveaux commentaires se chargent
        time.sleep(COMMENT_LOAD_WAIT)




# Fonction pour convertir les dates relatives Facebook

def convertir_date_facebook(date_str):
    """Convertit une date Facebook en format JJ-MM-AAAA"""
    aujourd_hui = datetime.today()
    date_str = date_str.lower().strip()

    try:
        if "min" in date_str:
            minutes = int(re.search(r"(\d+)", date_str).group(1))
            date_finale = aujourd_hui - timedelta(minutes=minutes)

        elif "h" in date_str:
            heures = int(re.search(r"(\d+)", date_str).group(1))
            date_finale = aujourd_hui - timedelta(hours=heures)

        elif "j" in date_str:
            jours = int(re.search(r"(\d+)", date_str).group(1))
            date_finale = aujourd_hui - timedelta(days=jours)

        elif "sem" in date_str:
            semaines = int(re.search(r"(\d+)", date_str).group(1))
            date_finale = aujourd_hui - timedelta(weeks=semaines)

        elif re.match(r"\d{1,2} \w+", date_str):  # Exemple : "10 mai"
            try:
                date_finale = datetime.strptime(date_str + f" {aujourd_hui.year}", "%d %b %Y")
            except:  # noqa: E722
                date_finale = datetime.strptime(date_str + f" {aujourd_hui.year}", "%d %B %Y")

        else:
            return "Format inconnu"

        return date_finale.strftime("%d-%m-%Y")

    except Exception:
        return "Erreur de conversion"

def extract_comments(container):
    """Extraction des commentaires Facebook avec auteur, texte, date"""
    print("🚀 Début de l'extraction des commentaires...")
    data = []

    try:
        scroll_comment_container(container)

        # 👉 Sélecteur de blocs complets de commentaire (parent de auteur + texte)
        full_comment_blocks = container.find_elements(By.XPATH, ".//div[contains(@class,'xv55zj0')]")
        print(f"✅ {len(full_comment_blocks)} blocs de commentaires trouvés.")

        for i, block in enumerate(full_comment_blocks):
            try:
                # 🔎 Nom de l’auteur
                try:
                    author_element = block.find_element(By.XPATH, ".//a[.//span[@dir='auto']]")
                    author_name = author_element.text.strip()
                except:  # noqa: E722
                    author_name = "Auteur inconnu"

                # 🔎 Texte du commentaire
                try:
                    comment_element = block.find_element(By.XPATH, ".//div[@dir='auto']")
                    comment_text = comment_element.text.strip()
                except:  # noqa: E722
                    comment_text = ""

                if not comment_text or len(comment_text) <= 1:
                    continue

                # 🔎 Date
                try:
                    parent = block.find_element(By.XPATH, ".//ancestor::div[@role='article']")
                    date_element = parent.find_element(
                        By.XPATH,
                        ".//a[contains(@href, 'comment_id=') and (contains(@href, '/posts/') or contains(@href, '/videos/'))]"
                    )
                    raw_date = date_element.text.strip()
                    formatted_date = convertir_date_facebook(raw_date)
                except:  # noqa: E722
                    formatted_date = "Date non trouvée"

                # ✅ Enregistrement
                data.append({
                    "date": formatted_date,
                    "auteur": author_name,
                    "source": "page_sgci",
                    "commentaire": comment_text
                })

            except Exception as e:
                print(f"⚠️ Erreur lors du traitement du bloc {i}: {e}")

        print(f"✅ Total des commentaires extraits: {len(data)}")

    except Exception as e:
        print(f"❌ Erreur générale lors de l'extraction: {e}")

    return data

def main():
    print("🚀 Démarrage du scraper Facebook multi-groupes...")

    try:
        if not load_cookies():
            print("❌ Impossible de charger les cookies")
            return

        all_data = []

        for url, source in zip(URLS, SOURCES):
            print(f"\n🔗 Accès à la source: {source}")
            driver.get(url)
            time.sleep(5)

            if not verify_login():
                print("❌ Vous n'êtes pas connecté!")
                return

            wait_for_facebook_page_loaded()
            comments_data = scroll_page_and_load_content()

            if not comments_data:
                print(f"❌ Aucun commentaire extrait pour {source}")
                continue

            # Ajouter la source actuelle à chaque ligne
            for c in comments_data:
                c["source"] = source

            all_data.extend(comments_data)
            print(f"✅ {len(comments_data)} commentaires récupérés depuis {source}")

        # Sauvegarde finale
        if not all_data:
            print("❌ Aucun commentaire extrait depuis toutes les sources.")
            return

        df = pd.DataFrame(all_data).drop_duplicates()
        filename = "facebook_commentaires_concatene.csv"
        df_concat = pd.concat([data, df], ignore_index=True).drop_duplicates()
        df_concat.to_csv(filename, index=False)

        print("\n✅ Extraction terminée pour toutes les sources.")
        print(f"📁 Fichier sauvegardé: {filename}")
        print(f"📊 Nombre total de commentaires: {len(df)}")

    except KeyboardInterrupt:
        print("\n⚠️ Arrêt demandé par l'utilisateur")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
    finally:
        print("🔚 Fermeture du navigateur...")
        driver.quit()

if __name__ == "__main__":
    main()
