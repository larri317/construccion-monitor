"""
scraper.py — Recolector de precios para el monitor de construcción.

Cada entrada de STORES define:
  - store      : nombre identificativo (tienda + producto)
  - url        : URL de la página del producto
  - product    : clave del producto (debe existir en PRICE_RANGES)
  - brand      : marca (Sika / Bostik / Soudal / Quilosa / Penosil / Mapei...)
  - category   : "Selladores" o "Espumas"
  - selectors  : lista de selectores CSS para encontrar el precio
                 (se prueban en orden hasta que uno funcione)

PRICE_RANGES define el rango de precio válido (€) por producto.
Si el scraper encuentra un número fuera de ese rango, lo descarta
(evita coger precios de envío, descuentos o de otros productos de la página).
"""

import re
import time
import random
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}

# ---------------------------------------------------------------------------
# Rango de precio válido (€) por producto. Ajusta si conoces el precio real.
# Si el número extraído cae fuera del rango, se descarta.
# ---------------------------------------------------------------------------
PRICE_RANGES = {
    # --- Selladores (cartucho 300 ml) ---
    "SIKAFLEX_11FC":        (5, 35),
    "BOSTIK_P795":          (5, 30),
    "BOSTIK_P360":          (5, 25),
    "SOUDAL_SOUDASEAL":     (5, 25),
    "MAPEI_PU45":           (5, 25),
    # --- Espumas (750 ml) ---
    "SIKABOOM_180":         (4, 20),
    "SIKABOOM_580":         (5, 22),
    "SIKABOOM_151":         (5, 22),
    "SIKABOOM_582":         (4, 20),
    "SIKABOOM_584":         (4, 20),
    "SIKABOOM_420_FIRE":    (8, 30),
    "QUILOSA_ORBAFOAM_CAN": (4, 18),
    "QUILOSA_ORBAFOAM_PIS": (5, 20),
    "QUILOSA_ORBAFOAM_TEJ": (4, 18),
    "QUILOSA_FIRESTOP":     (8, 25),
    "SOUDAL_SOUDAFOAM_CAN": (4, 18),
    "SOUDAL_SOUDAFOAM_PIS": (5, 20),
    "SOUDAL_SOUDAFOAM_FR":  (8, 25),
    "PENOSIL_PISTOLA":      (5, 20),
}

# ---------------------------------------------------------------------------
# Tiendas a rastrear. Añade/edita libremente.
# IMPORTANTE: cada URL debe ser la página de UN producto concreto.
# Los selectors son los habituales; si una tienda da precios raros,
# inspecciona el precio en Chrome (clic derecho → Inspeccionar) y
# añade el selector exacto al principio de la lista de esa entrada.
# ---------------------------------------------------------------------------
STORES = [
    # ===================== SELLADORES =====================
    # --- Sika Sikaflex 11 FC Purform ---
    {
        "store": "Campollano Sikaflex11FC",
        "url": "https://www.ferreteriacampollano.com/sellador-poliuretano-sikaflex-11fc-blanco-300ml-sika.html",
        "product": "SIKAFLEX_11FC", "brand": "Sika", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".product-price .price", ".price", ".product-price"],
    },
    {
        "store": "Rotuvall Sikaflex11FC",
        "url": "https://www.rotuvall.es/tienda/suministros-y-utillaje/adhesivos-y-pegamentos-industriales/sikaflex-11fc-purform-300cc/",
        "product": "SIKAFLEX_11FC", "brand": "Sika", "category": "Selladores",
        "selectors": [".woocommerce-Price-amount", "[itemprop='price']", ".price"],
    },
    {
        "store": "Esteba Sikaflex11FC",
        "url": "https://www.esteba.com/es/sellador-adhesivo-sikaflex-11fc-2",
        "product": "SIKAFLEX_11FC", "brand": "Sika", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".product-price", ".price"],
    },

    # --- Bostik P795 Poliuretano Premium ---
    {
        "store": "Campollano BostikP795",
        "url": "https://www.ferreteriacampollano.com/sellador-poliuretano-bostik-p795-premium.html",
        "product": "BOSTIK_P795", "brand": "Bostik", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".product-price .price", ".price"],
    },

    # --- Bostik P360 / Seal N Flex ---
    {
        "store": "Bricolemar BostikP360",
        "url": "https://www.bricolemar.com/adhesivos/bostik-seal-flex-p360.html",
        "product": "BOSTIK_P360", "brand": "Bostik", "category": "Selladores",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },

    # --- Soudal Soudaseal / Soudaflex ---
    {
        "store": "Bricolemar Soudaseal",
        "url": "https://www.bricolemar.com/adhesivos/soudal-soudaseal-240-fc.html",
        "product": "SOUDAL_SOUDASEAL", "brand": "Soudal", "category": "Selladores",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },

    # --- Mapei Mapeflex PU45 ---
    {
        "store": "Bricolemar MapeiPU45",
        "url": "https://www.bricolemar.com/adhesivos/mapei-mapeflex-pu45.html",
        "product": "MAPEI_PU45", "brand": "Mapei", "category": "Selladores",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },

    # ===================== ESPUMAS =====================
    # --- Sika Boom 180 (cánula) ---
    {
        "store": "Ferrokey SikaBoom180",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-sikaboom-180-canula-750-ml",
        "product": "SIKABOOM_180", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 580 (pistola) ---
    {
        "store": "Ferrokey SikaBoom580",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-sikaboom-580-pistola-750-ml",
        "product": "SIKABOOM_580", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 151 Multiposition ---
    {
        "store": "Ferrokey SikaBoom151",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-sikaboom-151-multiposition-750-ml",
        "product": "SIKABOOM_151", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 582 (tejas) ---
    {
        "store": "Ferrokey SikaBoom582",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-sikaboom-582-tejas-750-ml",
        "product": "SIKABOOM_582", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 584 (tejas) ---
    {
        "store": "Ferrokey SikaBoom584",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-sikaboom-584-tejas-750-ml",
        "product": "SIKABOOM_584", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 420 Fire (ignífuga) ---
    {
        "store": "Ferrokey SikaBoom420Fire",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-ignifuga-sikaboom-420-fire-750-ml",
        "product": "SIKABOOM_420_FIRE", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Competidores ESPUMAS ---
    {
        "store": "Bricolemar Orbafoam Canula",
        "url": "https://www.bricolemar.com/espuma-poliuretano/1827-quilosa-orbafoam-espuma-poliuretano-750ml-canula.html",
        "product": "QUILOSA_ORBAFOAM_CAN", "brand": "Quilosa", "category": "Espumas",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },
    {
        "store": "Campollano Orbafoam Pistola",
        "url": "https://www.ferreteriacampollano.com/espuma-de-poliuretano-pistola-orbafoam-fijacion-60-750ml-quilosa.html",
        "product": "QUILOSA_ORBAFOAM_PIS", "brand": "Quilosa", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".product-price .price", ".price"],
    },
    {
        "store": "Modrego Soudafoam FR Pistola",
        "url": "https://www.modregohogar.com/ferreteria/silicona/espumas-de-poliuretano/espuma-poliuretano-soudal-soudafoam-fr-pistola-750ml.html",
        "product": "SOUDAL_SOUDAFOAM_FR", "brand": "Soudal", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".product-price .price", ".price"],
    },
    {
        "store": "Ferrokey Soudafoam Pistola",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-universal-pistola-soudal-750-ml",
        "product": "SOUDAL_SOUDAFOAM_PIS", "brand": "Soudal", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },
    {
        "store": "Ferrokey Penosil Pistola",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-ultra-rapida-123-pistola-870-ml-penosil",
        "product": "PENOSIL_PISTOLA", "brand": "Penosil", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },
]


def _parse_price(text):
    """Extrae el primer número con formato de precio de un texto."""
    if not text:
        return None
    # admite 12,95 / 12.95 / 1.234,56
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})*,\d{2}|\d+[.,]\d{2}|\d+)", text)
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(".", "").replace(",", ".") \
        if "," in m.group(1) else m.group(1).replace(",", ".")
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _in_range(product, price):
    lo, hi = PRICE_RANGES.get(product, (0, 10_000))
    return price is not None and lo <= price <= hi


def scrape_store(entry, timeout=20):
    """Devuelve el precio (float) de una tienda o None si no se encuentra."""
    try:
        resp = requests.get(entry["url"], headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  ✗ {entry['store']}: error de red ({exc})")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1) selectores específicos
    for sel in entry["selectors"]:
        for node in soup.select(sel):
            price = _parse_price(node.get("content") or node.get_text())
            if _in_range(entry["product"], price):
                return price

    # 2) fallback: meta itemprop price
    meta = soup.find("meta", attrs={"itemprop": "price"})
    if meta:
        price = _parse_price(meta.get("content"))
        if _in_range(entry["product"], price):
            return price

    # 3) fallback: el menor precio dentro de rango en toda la página
    candidates = []
    for token in re.findall(r"\d+[.,]\d{2}", resp.text):
        p = _parse_price(token)
        if _in_range(entry["product"], p):
            candidates.append(p)
    if candidates:
        return min(candidates)

    print(f"  ✗ {entry['store']}: sin precio válido en rango")
    return None


def scrape_all():
    """Rastrea todas las tiendas y devuelve una lista de dicts."""
    rows = []
    for entry in STORES:
        price = scrape_store(entry)
        if price is not None:
            print(f"  ✓ {entry['store']}: {price:.2f} €")
            rows.append({
                "store": entry["store"],
                "product": entry["product"],
                "brand": entry["brand"],
                "category": entry["category"],
                "price": price,
            })
        time.sleep(random.uniform(1.0, 2.5))  # cortesía con las webs
    return rows


if __name__ == "__main__":
    for r in scrape_all():
        print(r)
