import time
import json
import re
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from unidecode import unidecode
import requests
from PIL import Image
from io import BytesIO
import pytesseract

# ========== CONFIGURATION ==========
GROUP_URL = "https://www.facebook.com/groups/656390831772336"
MAX_SCROLL_ATTEMPTS = 7
SCROLL_WAIT_TIME = 3
COMMENT_LOAD_WAIT = 4
MOTS_CLES = ["sgci","SGBCI","SGCi" "société générale", "la générale", "sgbci", "societe generale", 
             "la generale", "#SGCI", "#sgci", "la general", "#sociétéGénérale", 
             "SGCONNECT", "SG CONNECT", "sgconnect","Société générale"]

# ========== INITIALISATION ==========
path_edge = "./"
options = EdgeOptions()
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_argument("--disable-dev-shm-usage")
driver_path = path_edge + "edgedriver_win64/msedgedriver.exe"
driver = webdriver.Edge(service=EdgeService(executable_path=driver_path), options=options)

try:
    data_existante = pd.read_csv("postes.csv")
except FileNotFoundError:
    data_existante = pd.DataFrame()


# ========== FONCTIONS UTILITAIRES ==========
def load_cookies():
    """Charger et injecter les cookies Facebook"""
    try:
        driver.get("https://web.facebook.com")
        time.sleep(3)
        
        with open("facebook_cookies.json", "r", encoding="utf-8") as file:
            cookies = json.load(file)
        
        print(f"📁 {len(cookies)} cookies chargés")
        
        for cookie in cookies:
            for key in ["sameSite", "storeId", "id", "hostOnly", "session"]:
                cookie.pop(key, None)
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"⚠️ Cookie {cookie.get('name', '?')}: {e}")
        
        print("✅ Cookies injectés")
        return True
        
    except FileNotFoundError:
        print("❌ facebook_cookies.json introuvable!")
        return False
    except Exception as e:
        print(f"❌ Erreur cookies: {e}")
        return False


def verify_login():
    """Vérifier la connexion Facebook"""
    login_indicators = [
        "//input[@name='email']",
        "//input[@name='pass']",
        "//a[contains(text(), 'Se connecter')]"
    ]
    
    for indicator in login_indicators:
        if driver.find_elements(By.XPATH, indicator):
            return False
    return True


def wait_for_page_load(timeout=60):
    """Attendre le chargement complet de la page"""
    print("🔄 Chargement de la page...")
    
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        print("✅ Page chargée")
    except TimeoutException:
        print("⚠️ Timeout chargement")
    
    time.sleep(3)  # Sécurité supplémentaire


def convertir_date_facebook(date_str):
    """Convertit une date Facebook en JJ-MM-AAAA"""
    aujourd_hui = datetime.today()
    date_str = date_str.lower().strip()
    
    mois = {
        "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, 
        "décembre": 12, "decembre": 12
    }
    
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
        elif "ans" in date_str or "an" in date_str:
            annees = int(re.search(r"(\d+)", date_str).group(1))
            date_finale = aujourd_hui - timedelta(days=annees * 365)
        elif re.match(r"\d{1,2} \w+", date_str):
            date_str = re.sub(r"\s*à\s*\d{1,2}:\d{2}", "", date_str).strip()
            parts = date_str.split()
            if len(parts) >= 2:
                jour = int(parts[0])
                mois_str = unidecode(parts[1])
                mois_num = mois.get(mois_str.lower())
                if mois_num:
                    date_finale = datetime(aujourd_hui.year, mois_num, jour)
                else:
                    return "Format inconnu"
            else:
                return "Format inconnu"
        else:
            return "Format inconnu"
        
        return date_finale.strftime("%d-%m-%Y")
    
    except Exception:
        return "Erreur conversion"


def nettoyer_texte(texte):
    """Nettoie et normalise un texte"""
    texte = unidecode(texte).lower()
    texte = re.sub(r'[^\w\s]', ' ', texte)
    texte = re.sub(r'\s+', ' ', texte).strip()
    return texte


def contient_mot_cle(texte):
    """Vérifie si le texte contient un mot-clé"""
    texte_clean = nettoyer_texte(texte)
    return any(mot.lower() in texte_clean for mot in MOTS_CLES)


def extract_text_from_image_url(image_url):
    """OCR sur une image depuis URL"""
    try:
        print(f"🖼️ OCR sur: {image_url[:60]}...")
        response = requests.get(image_url, timeout=10)
        if response.status_code != 200:
            return ""
        
        image = Image.open(BytesIO(response.content)).convert('L')
        text = pytesseract.image_to_string(image, lang='fra+eng')
        text_clean = nettoyer_texte(text)
        
        print(f"🔤 OCR: {text_clean[:80]}...")
        return text_clean
    
    except Exception as e:
        print(f"⚠️ Erreur OCR: {e}")
        return ""


# ========== EXTRACTION DES POSTS ==========
def extraire_texte_post(post):
    """
    🔥 FONCTION CORRIGÉE - Extraction robuste du texte d'un post
    Utilise plusieurs sélecteurs en cascade pour s'adapter aux changements de Facebook
    """
    selecteurs = [
        # Sélecteurs pour le texte complet
        "div[data-ad-comet-preview='message']",
        "div[data-ad-preview='message']",
        "div.xdj266r.x11i5rnm.xat24cr.x1mh8g0r.x1vvkbs",
        "div.x1iorvi4.x1pi30zi.x1l90r2v.x1swvt13",
        "div[dir='auto'][style*='text-align']",
        
        # Sélecteurs pour spans de texte
        "span[dir='auto']",
        "div[class*='x1lliihq'] span",
        
        # Dernier recours: tout div avec du texte
        "div[role='article'] div[dir='auto']"
    ]
    
    textes_trouves = []
    
    for selecteur in selecteurs:
        try:
            elements = post.find_elements(By.CSS_SELECTOR, selecteur)
            for elem in elements:
                texte = elem.text.strip()
                if texte and len(texte) > 10:  # Ignore les textes trop courts
                    textes_trouves.append(texte)
        except:  # noqa: E722
            continue
    
    # Retourne le texte le plus long trouvé
    if textes_trouves:
        texte_final = max(textes_trouves, key=len)
        print(f"✅ Texte extrait ({len(texte_final)} caractères)")
        return texte_final
    
    print("⚠️ Aucun texte trouvé avec les sélecteurs")
    return None


def cliquer_voir_plus(post):
    """Clique sur 'Voir plus' si présent"""
    try:
        voir_plus = post.find_element(
            By.XPATH,
            ".//div[@role='button' and (contains(text(), 'Voir plus') or contains(text(), 'En voir plus'))]"
        )
        if voir_plus.is_displayed():
            driver.execute_script("arguments[0].click();", voir_plus)
            time.sleep(1)
            print("📌 'Voir plus' cliqué")
            return True
    except:  # noqa: E722
        pass
    return False


def extraire_auteur_date(post):
    """Extrait l'auteur et la date du post"""
    try:
        # Date
        date_element = post.find_element(
            By.XPATH,
            ".//a[contains(@href, '/posts/') or contains(@href, '/permalink/')]"
        )
        date_str = date_element.text.strip()
        date_formatee = convertir_date_facebook(date_str)
        
        # Auteur - plusieurs sélecteurs possibles
        auteur = "Auteur inconnu"
        selecteurs_auteur = [
            "div.xu06os2.x1ok221b",
            "a[role='link'] span",
            "h2 a span",
            "strong a span"
        ]
        
        for sel in selecteurs_auteur:
            try:
                elem = post.find_element(By.CSS_SELECTOR, sel)
                auteur = elem.text.strip().split("·")[0].strip()
                if auteur and len(auteur) > 2:
                    break
            except:   # noqa: E722
                continue
        
        print(f"📆 {date_formatee} - 👤 {auteur}")
        return date_formatee, auteur
    
    except:  # noqa: E722
        return None, "Auteur inconnu"


def analyser_images_post(post):
    """Analyse les images d'un post avec OCR"""
    try:
        images = post.find_elements(By.TAG_NAME, "img")
        print(f"🖼️ Analyse de {len(images)} image(s)...")
        
        for img in images:
            src = img.get_attribute("src")
            # Filtrer les petites icônes
            if not src or "emoji" in src or "static.xx.fbcdn" in src or "scontent" not in src:
                continue
            
            ocr_text = extract_text_from_image_url(src)
            if ocr_text and contient_mot_cle(ocr_text):
                print("✅ Mot-clé détecté dans image!")
                return True
        
        return False
    
    except Exception as e:
        print(f"⚠️ Erreur analyse images: {e}")
        return False


# ========== EXTRACTION DES COMMENTAIRES ==========
def ouvrir_commentaires(post):
    """Ouvre le panneau de commentaires"""
    try:
        # Plusieurs sélecteurs pour le bouton commentaires
        selecteurs_btn = [
            "div[id^='_r_'][role='button']",
            "div[aria-label*='commentaire']",
            "div[aria-label*='Commentaire']"
        ]
        
        for sel in selecteurs_btn:
            try:
                btn = post.find_element(By.CSS_SELECTOR, sel)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                print("💬 Panneau commentaires ouvert")
                return True
            except:  # noqa: E722
                continue
        
        print("⚠️ Bouton commentaires introuvable")
        return False
    
    except Exception as e:
        print(f"⚠️ Erreur ouverture commentaires: {e}")
        return False


def trouver_container_commentaires():
    """Trouve le container de commentaires avec plusieurs sélecteurs"""
    selecteurs = [
        "div.html-div.x14z9mp.xat24cr.x1lziwak.xexx8yu.xyri2b.x18d9i69.x1c1uobl.x1gslohp",
        "div[role='dialog'] div[class*='x14z9mp']",
        "div[aria-label*='commentaire']",
        "div.x78zum5.xdt5ytf.x1iyjqo2"
    ]
    
    for sel in selecteurs:
        try:
            container = driver.find_element(By.CSS_SELECTOR, sel)
            print(f"✅ Container trouvé: {sel[:50]}...")
            return container
        except:  # noqa: E722
            continue
    
    print("❌ Container commentaires introuvable")
    return None


def scroll_commentaires(container):
    """Scroll le container de commentaires"""
    print("🔄 Scroll des commentaires...")
    prev_count = 0
    
    for _ in range(5):  # Max 5 scrolls
        current_count = len(container.find_elements(By.XPATH, "./*"))
        
        if current_count == prev_count:
            print(f"✅ Scroll terminé: {current_count} éléments")
            break
        
        prev_count = current_count
        print(f"📊 {current_count} éléments")
        
        driver.execute_script("""
            var c = arguments[0];
            if (c.lastElementChild) {
                c.lastElementChild.scrollIntoView({behavior: 'instant', block: 'end'});
            }
        """, container)
        
        time.sleep(COMMENT_LOAD_WAIT)


def extraire_commentaires(container):
    """Extraction des commentaires depuis le container"""
    print("🚀 Extraction des commentaires...")
    commentaires = []
    
    try:
        scroll_commentaires(container)
        
        # Plusieurs sélecteurs pour les blocs de commentaires
        selecteurs_blocs = [
            ".//div[contains(@class,'xv55zj0')]",
            ".//div[@role='article']",
            ".//div[contains(@class, 'x1lliihq')]"
        ]
        
        blocs = []
        for sel in selecteurs_blocs:
            try:
                blocs = container.find_elements(By.XPATH, sel)
                if blocs:
                    print(f"✅ {len(blocs)} blocs trouvés avec: {sel}")
                    break
            except:  # noqa: E722
                continue
        
        if not blocs:
            print("❌ Aucun bloc de commentaire trouvé")
            return []
        
        for i, bloc in enumerate(blocs):
            try:
                # Auteur
                try:
                    auteur_elem = bloc.find_element(By.XPATH, ".//a[.//span[@dir='auto']]")
                    auteur = auteur_elem.text.strip()
                except:  # noqa: E722
                    auteur = "Auteur inconnu"
                
                # Texte
                try:
                    texte_elem = bloc.find_element(By.XPATH, ".//div[@dir='auto']")
                    texte = texte_elem.text.strip()
                except:  # noqa: E722
                    texte = ""
                
                if not texte or len(texte) <= 1:
                    continue
                
                # Date
                try:
                    parent = bloc.find_element(By.XPATH, ".//ancestor::div[@role='article']")
                    date_elem = parent.find_element(
                        By.XPATH,
                        ".//a[contains(@href, 'comment_id=')]"
                    )
                    date_brute = date_elem.text.strip()
                    date_fmt = convertir_date_facebook(date_brute)
                except:  # noqa: E722
                    date_fmt = "Date inconnue"
                
                commentaires.append({
                    "date": date_fmt,
                    "auteur_com": auteur,
                    "source": "OLBCI",
                    "commentaire": texte
                })
            
            except Exception as e:
                print(f"⚠️ Erreur bloc {i}: {e}")
        
        print(f"✅ {len(commentaires)} commentaires extraits")
        return commentaires
    
    except Exception as e:
        print(f"❌ Erreur extraction: {e}")
        return []


def fermer_container():
    """Ferme le container de commentaires"""
    for btn in driver.find_elements(By.CSS_SELECTOR, "div[aria-label='Fermer']"):
        try:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1)
                print("✅ Container fermé")
                return
        except:  # noqa: E722
            continue


# ========== FONCTION PRINCIPALE D'ANALYSE ==========
def analyser_posts():
    """Analyse tous les posts visibles et extrait les commentaires pertinents"""
    print("🔄 Analyse des posts...")
    tous_commentaires = []
    
    posts = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
    print(f"🔍 {len(posts)} posts trouvés")
    
    for i in range(len(posts)):
        try:
            print(f"\n🧩 === POST {i+1}/{len(posts)} ===")
            
            # Recharger la liste (protection contre StaleElement)
            posts = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
            if i >= len(posts):
                break
            post = posts[i]
            
            # Cliquer sur "Voir plus"
            cliquer_voir_plus(post)
            
            # Extraire le texte
            texte_post = extraire_texte_post(post)
            if not texte_post:
                print("⛔ Texte introuvable, post ignoré")
                continue
            
            # Extraire auteur et date
            date_post, auteur_post = extraire_auteur_date(post)
            
            # Vérifier mot-clé dans le texte
            mot_cle_texte = contient_mot_cle(texte_post)
            mot_cle_image = False
            
            if not mot_cle_texte:
                mot_cle_image = analyser_images_post(post)
            
            if not mot_cle_texte and not mot_cle_image:
                print("⛔ Aucun mot-clé détecté, post ignoré")
                continue
            
            print("✅ Mot-clé détecté! Extraction des commentaires...")
            
            # Ouvrir les commentaires
            if not ouvrir_commentaires(post):
                continue
            
            # Trouver le container
            container = trouver_container_commentaires()
            if not container:
                fermer_container()
                continue
            
            # Extraire les commentaires
            commentaires = extraire_commentaires(container)
            
            # Ajouter les infos du post
            for com in commentaires:
                com["poste"] = texte_post[:200]  # Limiter la taille
                com["date_post"] = date_post
                com["auteur"] = auteur_post
            
            tous_commentaires.extend(commentaires)
            
            # Fermer le container
            fermer_container()
        
        except StaleElementReferenceException:
            print(f"⚠️ Post {i} obsolète, on continue")
            continue
        except Exception as e:
            print(f"⚠️ Erreur post {i}: {e}")
            continue
    
    return tous_commentaires


def scroll_et_charger():
    """Scroll la page et analyse les posts à chaque étape"""
    print("🔄 Scroll et chargement...")
    tous_commentaires = []
    
    for i in range(MAX_SCROLL_ATTEMPTS):
        print(f"\n📜 === SCROLL {i+1}/{MAX_SCROLL_ATTEMPTS} ===")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_WAIT_TIME)
        
        # Analyser les posts actuellement visibles
        commentaires = analyser_posts()
        tous_commentaires.extend(commentaires)
    
    print(f"\n✅ Scroll terminé - {len(tous_commentaires)} commentaires collectés")
    return tous_commentaires


# ========== FONCTION MAIN ==========
def main():
    """Fonction principale"""
    print("🚀 Démarrage du scraper Facebook...\n")
    
    try:
        # 1. Cookies
        if not load_cookies():
            print("❌ Impossible de charger les cookies")
            return
        
        # 2. Accès au groupe
        print(f"🔗 Accès au groupe: {GROUP_URL}")
        driver.get(GROUP_URL)
        
        # 3. Vérification connexion
        if not verify_login():
            print("❌ Vous n'êtes pas connecté!")
            return
        print("✅ Connexion vérifiée")
        
        # 4. Attendre chargement
        wait_for_page_load()
        time.sleep(10)
        
        # 5. Scroll et extraction
        commentaires = scroll_et_charger()
        
        if not commentaires:
            print("❌ Aucun commentaire extrait")
            return
        
        # 6. Sauvegarde
        df = pd.DataFrame(commentaires)
        df = df.drop_duplicates()
        
        if not data_existante.empty:
            df = pd.concat([data_existante, df], ignore_index=True).drop_duplicates()
        
        df.to_csv("postes.csv", index=False, encoding='utf-8-sig')
        
        print("\n✅ Extraction terminée!")
        print("📁 Fichier: postes.csv")
        print(f"📊 Commentaires: {len(df)}")
        
        # Aperçu
        print("\n📝 Aperçu des commentaires:")
        for i, com in enumerate(commentaires[:3]):
            print(f"{i+1}. [{com['auteur_com']}] {com['commentaire'][:80]}...")
    
    except KeyboardInterrupt:
        print("\n⚠️ Arrêt demandé")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🔚 Fermeture du navigateur...")
        driver.quit()


if __name__ == "__main__":
    main()