import csv
import os
import time
import json
import re
import random
import pandas as pd
from datetime import datetime, timedelta, timezone
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ─────────────────────────────────────────────
# CONFIGURATION
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

MAX_SCROLL_ATTEMPTS   = 3
SCROLL_WAIT_TIME      = 4
COMMENT_LOAD_WAIT     = 3
OUTPUT_FILE           = "facebook_commentaires_concatene.csv"
DATE_FALLBACK_LOG_FILE = "facebook_date_fallbacks.csv"

_FB_DEBUG_DOM = os.environ.get("FB_DEBUG_DOM", "").strip() in ("1", "true", "yes", "on")

_ISO_DATE_RX = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
    re.I,
)

# ─────────────────────────────────────────────
# VALIDATION DATE — LE FIX PRINCIPAL
# ─────────────────────────────────────────────
# Mots qui indiquent qu'une chaîne est une date
_DATE_KEYWORDS = re.compile(
    r"""
    \d{4}-\d{2}-\d{2}           # ISO 8601
    | \d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}  # DD/MM/YYYY
    | \b\d+\s*(
        min|minute|minutes|mn
        |h\b|hr|heure|heures|hour|hours
        |j\b|jour|jours|day|days
        |sem|semaine|semaines|week|weeks
        |mois|month|months
        |an\b|ans\b|year|years
      )
    | \b(il\s+y\s+a|ago|yesterday|hier|today|aujourd)
    | \b(janvier|février|fevrier|mars|avril|mai|juin
        |juillet|août|aout|septembre|octobre|novembre
        |décembre|decembre
        |january|february|march|april|june|july|august
        |september|october|november|december)
    """,
    re.IGNORECASE | re.VERBOSE,
)

def ressemble_a_une_date(texte: str) -> bool:
    """
    Retourne True si le texte ressemble à une date ou durée.
    Évite de confondre un nom de personne avec une date.
    """
    if not texte:
        return False
    return bool(_DATE_KEYWORDS.search(texte))


# ─────────────────────────────────────────────
# UTILITAIRES JSON / ISO
# ─────────────────────────────────────────────
def _unix_ts_vers_iso_brute(ts: int) -> str:
    if ts > 10_000_000_000:
        ts //= 1000
    if 946684800 < ts < 4_102_444_800:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ""


def _iso_depuis_texte(blob: str) -> str:
    if not blob:
        return ""
    m = _ISO_DATE_RX.search(blob)
    return m.group(0) if m else ""


def _timestamps_depuis_json_brut(text: str) -> str:
    if not text:
        return ""
    for m in re.finditer(
        r'"(?:creation_time|created_time|publish_time|comment_timestamp|time)"\s*:\s*(\d{10,16})\b',
        text,
    ):
        iso = _unix_ts_vers_iso_brute(int(m.group(1)))
        if iso:
            return iso
    return ""


def _date_depuis_attribut_data_store(raw: str) -> str:
    if not raw or len(raw) > 500_000:
        return ""
    iso = _timestamps_depuis_json_brut(raw)
    if iso:
        return iso
    iso = _iso_depuis_texte(raw)
    if iso:
        return iso
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for k, v in item.items():
                lk = str(k).lower()
                if lk in ("creation_time", "created_time", "publish_time",
                          "comment_timestamp", "timestamp"):
                    if isinstance(v, (int, float)):
                        iso = _unix_ts_vers_iso_brute(int(v))
                        if iso:
                            return iso
                    if isinstance(v, str):
                        iso = _iso_depuis_texte(v)
                        if iso:
                            return iso
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(item, list):
            stack.extend(item)
    return ""


def _date_via_js_sous_arbre(driver, webelement) -> str:
    """Scan JS du sous-arbre pour trouver une date dans les attributs."""
    try:
        blob = driver.execute_script(
            r"""
            const root = arguments[0];
            const out = [];
            const nodes = root.querySelectorAll('*');
            for (let i = 0; i < nodes.length; i++) {
                const el = nodes[i];
                for (const attr of ['datetime', 'data-store', 'data-ft', 'title', 'aria-label']) {
                    const v = el.getAttribute(attr);
                    if (v && v.length > 0 && v.length < 15000) out.push(v);
                }
            }
            return out.join('\n');
            """,
            webelement,
        )
    except Exception:
        return ""
    if not blob:
        return ""
    iso = _iso_depuis_texte(blob)
    if iso:
        return iso
    iso = _timestamps_depuis_json_brut(blob)
    if iso:
        return iso
    for line in blob.split("\n"):
        if "time" in line.lower() or "creation" in line.lower():
            iso = _date_depuis_attribut_data_store(line)
            if iso:
                return iso
    return ""


# ─────────────────────────────────────────────
# DÉLAIS
# ─────────────────────────────────────────────
def human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))


# ─────────────────────────────────────────────
# NAVIGATEUR
# ─────────────────────────────────────────────
options = EdgeOptions()
options.add_argument("--start-maximized")
options.add_argument("--disable-notifications")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-infobars")
options.add_argument("--lang=fr-FR")
options.add_argument(
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"
)
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver_path = "./edgedriver_win64/msedgedriver.exe"
driver = webdriver.Edge(service=EdgeService(executable_path=driver_path), options=options)
driver.execute_cdp_cmd(
    "Page.addScriptToEvaluateOnNewDocument",
    {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
)


# ─────────────────────────────────────────────
# AUTHENTIFICATION
# ─────────────────────────────────────────────
def load_cookies():
    try:
        driver.get("https://www.facebook.com/")
        time.sleep(3)
        with open("facebook_cookies.json", "r", encoding="utf-8") as file:
            cookies = json.load(file)
        print(f"📁 {len(cookies)} cookies chargés")
        for cookie in cookies:
            for key in ["sameSite", "storeId", "id", "hostOnly", "session", "expirationDate"]:
                cookie.pop(key, None)
            if "domain" in cookie and not cookie["domain"].startswith("."):
                cookie["domain"] = "." + cookie["domain"].lstrip(".")
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        print("✅ Cookies injectés")
        return True
    except FileNotFoundError:
        print("❌ facebook_cookies.json introuvable !")
        return False
    except Exception as e:
        print(f"❌ Erreur cookies : {e}")
        return False


def verify_login():
    try:
        for indicator in ["//input[@name='email']", "//input[@name='pass']"]:
            if driver.find_elements(By.XPATH, indicator):
                return False
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# CHARGEMENT PAGE
# ─────────────────────────────────────────────
def wait_for_facebook_page_loaded(timeout=60):
    print("🔄 Chargement de la page...")
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        print("⚠️ Timeout readyState")

    for sel in ["div[role='main']", "div[role='article']",
                "div[data-pagelet='ProfileTimeline']", "div[data-pagelet='PageTimeline']"]:
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            print(f"✅ Page prête ({sel})")
            return True
        except TimeoutException:
            continue

    print("⚠️ Aucun sélecteur principal trouvé — on continue")
    human_delay(2, 4)
    return True


# ─────────────────────────────────────────────
# EXTRACTION DATE — CORRIGÉE
# ─────────────────────────────────────────────
def extraire_brute_date_commentaire(block, aria_label: str, driver=None) -> tuple[str, str]:
    """
    Retourne (chaîne_brute_pour_parse, origine).
    
    FIX PRINCIPAL : chaque valeur extraite est validée par ressemble_a_une_date()
    avant d'être retournée — évite de confondre un nom d'auteur avec une date.
    """

    # ── 1. Balises <time> ────────────────────────────────────────────
    try:
        for t in block.find_elements(By.CSS_SELECTOR, "time"):
            # Priorité : attribut datetime (le plus fiable)
            v = t.get_attribute("datetime")
            if v and v.strip() and ressemble_a_une_date(v.strip()):
                return v.strip(), "time"
            # Fallback : title
            v = t.get_attribute("title")
            if v and v.strip() and ressemble_a_une_date(v.strip()):
                return v.strip(), "time"
            # Fallback : texte visible
            tx = (t.text or "").strip()
            if tx and ressemble_a_une_date(tx):
                return tx, "time"
    except Exception:
        pass

    # ── 2. Lien comment_id ───────────────────────────────────────────
    # ⚠️ FIX : on valide que le texte/aria-label est bien une date,
    #          pas un nom de personne
    try:
        for a in block.find_elements(By.XPATH, ".//a[contains(@href,'comment_id')]"):
            # aria-label en priorité (souvent "il y a X j")
            for attr in ("aria-label", "title"):
                v = (a.get_attribute(attr) or "").strip()
                if v and ressemble_a_une_date(v):
                    return v, "link"
            # texte visible du lien
            tx = (a.text or "").strip()
            if tx and ressemble_a_une_date(tx):
                return tx, "link"
            # ⚠️ Si le texte ne ressemble PAS à une date → on ignore ce lien
    except Exception:
        pass

    # ── 3. aria-label du bloc commentaire ───────────────────────────
    if aria_label:
        al = aria_label.strip()
        # "Commentaire de X · il y a 5 j"
        for pat in [
            r"il y a\s+(.+?)(?:\s*[·•]\s*|\s*$)",
            r"hace\s+(.+?)(?:\s*[·•]\s*|\s*$)",
            r"([\d\w\s,'\-]+)\s+ago\b",
        ]:
            m = re.search(pat, al, re.IGNORECASE | re.DOTALL)
            if m:
                candidat = (m.group(1) or "").strip()
                if candidat and ressemble_a_une_date(candidat):
                    return candidat, "aria"
                # "il y a" trouvé mais la partie après n'est pas parseable →
                # retourner quand même pour que convertir_date_facebook tente
                if candidat:
                    return candidat, "aria"

    # ── 4. abbr[title] ───────────────────────────────────────────────
    try:
        for ab in block.find_elements(By.CSS_SELECTOR, "abbr[title]"):
            tit = (ab.get_attribute("title") or "").strip()
            if tit and ressemble_a_une_date(tit):
                return tit, "time"
    except Exception:
        pass

    # ── 5. data-store / data-ft (JSON avec timestamps) ──────────────
    try:
        for attr_name in ("data-store", "data-ft"):
            for el in block.find_elements(By.CSS_SELECTOR, f"[{attr_name}]"):
                raw = el.get_attribute(attr_name)
                if raw:
                    iso = _date_depuis_attribut_data_store(raw)
                    if iso:
                        return iso, "data_store"
    except Exception:
        pass

    # ── 6. Scan JS de tout le sous-arbre ────────────────────────────
    if driver is not None:
        iso = _date_via_js_sous_arbre(driver, block)
        if iso:
            return iso, "js"

    # ── 7. Recherche texte relatif visible dans les spans/liens ─────
    try:
        for el in block.find_elements(By.CSS_SELECTOR, "span, a"):
            txt = (el.text or "").strip()
            if txt and ressemble_a_une_date(txt) and len(txt) < 50:
                return txt, "texte_visible"
    except Exception:
        pass

    return "", ""


# ─────────────────────────────────────────────
# CONVERSION DATE
# ─────────────────────────────────────────────
MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2,
    "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}

NOMBRES_FR = {
    "un": "1", "une": "1", "deux": "2", "trois": "3", "quatre": "4",
    "cinq": "5", "six": "6", "sept": "7", "huit": "8", "neuf": "9",
    "dix": "10", "onze": "11", "douze": "12", "treize": "13",
    "quatorze": "14", "quinze": "15", "seize": "16", "dix-sept": "17",
    "dix-huit": "18", "dix-neuf": "19", "vingt": "20",
    "trente": "30", "quarante": "40", "cinquante": "50",
}


def _convertir_date_facebook_core(original: str, aujourd_hui: datetime) -> str | None:
    s = original.lower().strip()

    # Remplacer nombres en lettres
    for mot, chiffre in NOMBRES_FR.items():
        s = re.sub(rf'\b{mot}\b', chiffre, s, flags=re.IGNORECASE)

    try:
        # ISO 8601
        if re.match(r'\d{4}-\d{2}-\d{2}', original):
            return datetime.fromisoformat(
                original.replace("Z", "+00:00")
            ).strftime("%d-%m-%Y")

        # Extraire la durée après "il y a" ou avant "ago"
        duration_text = s
        m = re.search(r"il y a\s+(.+?)(?:\s*[·•]|$)", s, re.IGNORECASE)
        if m:
            duration_text = m.group(1).strip()
        else:
            m = re.search(r"(.+?)\s+ago", s, re.IGNORECASE)
            if m:
                duration_text = m.group(1).strip()

        # Minutes
        if re.search(r"\d+\s*(m\b|min|minute|minutes|mn)", duration_text):
            n = int(re.search(r"(\d+)", duration_text).group(1))
            return (aujourd_hui - timedelta(minutes=n)).strftime("%d-%m-%Y")

        # Heures
        if re.search(r"\d+\s*(h\b|hr\b|heure|heures|hour|hours)", duration_text):
            n = int(re.search(r"(\d+)", duration_text).group(1))
            return (aujourd_hui - timedelta(hours=n)).strftime("%d-%m-%Y")

        # Jours
        if re.search(r"\d+\s*(j\b|jour|jours|day|days|d\b)", duration_text):
            n = int(re.search(r"(\d+)", duration_text).group(1))
            return (aujourd_hui - timedelta(days=n)).strftime("%d-%m-%Y")

        # Semaines
        if re.search(r"\d+\s*(sem\b|semaine|semaines|week|weeks|w\b)", duration_text):
            n = int(re.search(r"(\d+)", duration_text).group(1))
            return (aujourd_hui - timedelta(weeks=n)).strftime("%d-%m-%Y")

        # Mois
        if re.search(r"\d+\s*(mois|month|months|mo\b)", duration_text):
            n = int(re.search(r"(\d+)", duration_text).group(1))
            return (aujourd_hui - timedelta(days=n * 30)).strftime("%d-%m-%Y")

        # Ans
        if re.search(r"\d+\s*(an\b|ans\b|year|years|y\b)", duration_text):
            n = int(re.search(r"(\d+)", duration_text).group(1))
            return (aujourd_hui - timedelta(days=n * 365)).strftime("%d-%m-%Y")

        # Hier
        if any(k in duration_text for k in ["hier", "yesterday"]):
            return (aujourd_hui - timedelta(days=1)).strftime("%d-%m-%Y")

        # Aujourd'hui
        if any(k in duration_text for k in ["aujourd", "today", "just now",
                                             "instant", "maintenant"]):
            return aujourd_hui.strftime("%d-%m-%Y")

        # Date absolue FR : "28 mars 2026"
        m = re.search(r"(\d{1,2})\s+([a-zéûôà]+)\s*(\d{4})?", s)
        if m:
            jour = int(m.group(1))
            mois_str = m.group(2).strip()
            annee = int(m.group(3)) if m.group(3) else aujourd_hui.year
            if mois_str in MOIS_FR:
                try:
                    return datetime(annee, MOIS_FR[mois_str], jour).strftime("%d-%m-%Y")
                except ValueError:
                    pass

        # Date absolue EN : "March 28, 2026"
        for fmt, append_year in (
            ("%B %d, %Y", False), ("%b %d, %Y", False),
            ("%B %d", True), ("%b %d", True),
        ):
            try:
                s_in = original.strip()
                if append_year:
                    d = datetime.strptime(f"{s_in} {aujourd_hui.year}", f"{fmt} %Y")
                else:
                    d = datetime.strptime(s_in, fmt)
                return d.strftime("%d-%m-%Y")
            except ValueError:
                continue

        # DD/MM/YYYY ou DD-MM-YYYY
        m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", s)
        if m:
            j, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if a < 100:
                a += 2000
            try:
                return datetime(a, mo, j).strftime("%d-%m-%Y")
            except ValueError:
                pass

        # YYYY/MM/DD
        m = re.match(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", s)
        if m:
            a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                return datetime(a, mo, j).strftime("%d-%m-%Y")
            except ValueError:
                pass

    except Exception:
        return None

    return None


def convertir_date_facebook(date_str: str | None) -> tuple[str, bool]:
    """
    Retourne (date JJ-MM-AAAA, repli_date_du_jour).
    repli_date_du_jour=True si aucun parse réussi.
    """
    aujourd_hui = datetime.today()
    original = (date_str or "").strip()
    if not original:
        return aujourd_hui.strftime("%d-%m-%Y"), True
    try:
        parsed = _convertir_date_facebook_core(original, aujourd_hui)
    except Exception:
        parsed = None
    if parsed:
        return parsed, False
    return aujourd_hui.strftime("%d-%m-%Y"), True


def append_date_fallback_csv(rows: list[dict]) -> None:
    cols = ["horodatage_run", "source_page", "ligne_lot", "motif",
            "brute_facebook", "date_appliquee", "auteur", "apercu_commentaire"]
    horo = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.isfile(DATE_FALLBACK_LOG_FILE)
    with open(DATE_FALLBACK_LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        for r in rows:
            w.writerow({**r, "horodatage_run": horo})


# ─────────────────────────────────────────────
# SCROLL + EXTRACTION
# ─────────────────────────────────────────────
def scroll_page_and_load_content():
    print(f"🔄 Scroll ({MAX_SCROLL_ATTEMPTS} passes)...")
    prev_count = 0

    for i in range(MAX_SCROLL_ATTEMPTS):
        print(f"  📜 Scroll {i+1}/{MAX_SCROLL_ATTEMPTS}")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_delay(SCROLL_WAIT_TIME, SCROLL_WAIT_TIME + 2)

        try:
            more_btns = driver.find_elements(
                By.XPATH,
                "//div[@role='button' and ("
                "contains(., 'Voir plus de commentaires') or "
                "contains(., 'Afficher plus de commentaires') or "
                "contains(., 'Voir 1 réponse') or "
                "contains(., 'View more comments') or "
                "contains(., 'commentaires supplementaires')"
                ")]"
            )
            for mb in more_btns:
                if mb.is_displayed():
                    driver.execute_script("arguments[0].click();", mb)
                    print("    📥 'Afficher plus' cliqué")
                    human_delay(2, 3)
        except Exception:
            pass

        current_count = len(driver.find_elements(
            By.XPATH,
            "//div[@role='article' and ("
            "contains(@aria-label,'Commentaire de') or "
            "contains(@aria-label,'Réponse de') or "
            "contains(@aria-label,'Comment by') or "
            "contains(@aria-label,'Reply by')"
            ")]"
        ))
        print(f"    💬 {current_count} commentaires visibles")
        if current_count == prev_count and i > 0:
            print("    ℹ️ Stable — scroll arrêté")
            break
        prev_count = current_count

    print("✅ Scroll terminé")
    return extraire_commentaires_depuis_page()


def extraire_commentaires_depuis_page() -> list:
    print("\n🔍 Extraction des commentaires depuis le DOM...")
    data = []
    seen = set()

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

    if _FB_DEBUG_DOM and comment_articles:
        try:
            sample = driver.execute_script(
                "return arguments[0].outerHTML;", comment_articles[0]
            )
            with open("fb_debug_comment_0.html", "w", encoding="utf-8") as f:
                f.write(sample or "")
            print("  🐛 fb_debug_comment_0.html sauvé")
        except Exception as e:
            print(f"  🐛 Debug impossible : {e}")

    stats_date = {"time": 0, "link": 0, "aria": 0, "data_store": 0,
                  "js": 0, "texte_visible": 0, "sans_indice_dom": 0}
    ligne_lot = 0

    for i, block in enumerate(comment_articles):
        try:
            aria_label = block.get_attribute("aria-label") or ""

            # ── Auteur ───────────────────────────────────────────────
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

            # ── Texte ────────────────────────────────────────────────
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

            key = f"{author_name}|{comment_text[:80]}"
            if key in seen:
                continue
            seen.add(key)

            # ── Date ─────────────────────────────────────────────────
            raw_date, origine = extraire_brute_date_commentaire(
                block, aria_label, driver=driver
            )

            # Comptage stats
            if origine in stats_date:
                stats_date[origine] += 1
            else:
                stats_date["sans_indice_dom"] += 1

            formatted_date, date_fallback = convertir_date_facebook(
                (raw_date or "").strip()
            )

            ligne_lot += 1
            row = {
                "date":        formatted_date,
                "auteur":      author_name,
                "source":      "",
                "commentaire": comment_text,
            }

            if date_fallback:
                brute = (raw_date or "").strip()
                row["_fb_date_fallback_info"] = {
                    "ligne_lot":       ligne_lot,
                    "motif":           "brute_vide" if not brute else "parse_echec",
                    "brute_facebook":  brute[:500] if brute else "",
                }

            data.append(row)

        except StaleElementReferenceException:
            print(f"  ⚠️ Bloc {i} périmé — ignoré")
        except Exception as e:
            print(f"  ⚠️ Erreur bloc {i} : {e}")

    n_fb = sum(1 for r in data if "_fb_date_fallback_info" in r)
    print(f"  ✅ {len(data)} commentaires valides extraits")
    print(
        f"  📅 Dates : <time>={stats_date['time']}, "
        f"lien={stats_date['link']}, aria={stats_date['aria']}, "
        f"data-store={stats_date['data_store']}, js={stats_date['js']}, "
        f"texte={stats_date['texte_visible']}, "
        f"sans indice DOM={stats_date['sans_indice_dom']}"
    )
    if n_fb:
        print(f"  ⚠️ Repli date du jour : {n_fb} commentaire(s)")

    return data


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("🚀 Démarrage du scraper Facebook (fix date — avril 2026)...")

    try:
        existing_data = pd.read_csv(OUTPUT_FILE)
        print(f"📂 {len(existing_data)} lignes existantes chargées")
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
                print("❌ Session expirée")
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
            human_delay(3, 6)

        if not all_data:
            print("\n❌ Aucun commentaire extrait — CSV non modifié")
            return

        # ── Journalisation des fallbacks ─────────────────────────────
        fallback_log = []
        for c in all_data:
            info = c.pop("_fb_date_fallback_info", None)
            if info:
                apercu = (c.get("commentaire") or "")[:120].replace("\n", " ")
                fallback_log.append({
                    "source_page":       c.get("source", ""),
                    "ligne_lot":         info["ligne_lot"],
                    "motif":             info["motif"],
                    "brute_facebook":    info.get("brute_facebook", ""),
                    "date_appliquee":    c.get("date", ""),
                    "auteur":            c.get("auteur", ""),
                    "apercu_commentaire": apercu,
                })

        if fallback_log:
            append_date_fallback_csv(fallback_log)
            print(f"\n⚠️ Dates remplacées par la date du jour : {len(fallback_log)}")
            for r in fallback_log:
                bf = (r["brute_facebook"] or "")[:45].replace("\n", " ")
                print(
                    f"  · {r['source_page']} | {r['motif']} "
                    f"| {r['auteur'][:30]} | brute={bf!r} | → {r['date_appliquee']}"
                )
            print(f"  📄 Journal : {DATE_FALLBACK_LOG_FILE}")

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
        import traceback
        traceback.print_exc()
    finally:
        print("🔚 Fermeture du navigateur...")
        driver.quit()


if __name__ == "__main__":
    main()