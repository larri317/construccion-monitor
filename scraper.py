"""
scraper.py — Recolector de precios para el monitor de construcción.

Novedades de esta versión
-------------------------
1) EXTRACCIÓN DE PRECIO MÁS ROBUSTA. Antes solo se miraban unos selectores CSS
   concretos; si la tienda cambiaba el HTML, el precio se perdía. Ahora se prueba,
   en este orden:
       a) JSON-LD  (<script type="application/ld+json"> → offers.price)  ← lo más fiable
       b) Microdatos (<meta itemprop="price">)
       c) Selectores CSS de la propia entrada
       d) Último recurso: el menor precio dentro de rango en toda la página
   La mayoría de tiendas (WooCommerce, PrestaShop, Shopify) publican el precio en
   JSON-LD, así que esto sobrevive a los cambios de maquetación.

2) INFORME DE DIAGNÓSTICO. Al terminar, imprime una tabla con el estado de CADA
   tienda (OK / HTTP 404 / bloqueado / sin precio). Así, si una URL se cae, lo ves
   al instante en el log de GitHub Actions en vez de que el producto desaparezca
   en silencio de la web.

Formato de salida (idéntico al anterior, no rompe main.py/database.py):
   scrape_all() -> lista de dicts {store, product, brand, category, price}
"""

import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}

# ---------------------------------------------------------------------------
# Rango de precio válido (€) por producto. Si el número extraído cae fuera del
# rango, se descarta (evita coger precios de envío, packs, IVA suelto, etc.).
# ---------------------------------------------------------------------------
PRICE_RANGES = {
    # --- Selladores (cartucho ~300 ml) ---
    "SIKAFLEX_11FC":        (5, 35),
    "BOSTIK_P795":          (4, 30),
    "BOSTIK_P360":          (4, 25),
    "SOUDAL_SOUDASEAL":     (4, 25),
    "MAPEI_PU45":           (4, 25),
    # --- Espumas (750 ml) ---
    "SIKABOOM_180":         (4, 20),
    "SIKABOOM_580":         (5, 22),
    "SIKABOOM_151":         (5, 22),
    "SIKABOOM_582":         (4, 22),
    "SIKABOOM_584":         (4, 22),
    "SIKABOOM_420_FIRE":    (8, 32),
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
# Tiendas a rastrear.
#   OK  = URL refrescada/verificada en esta revisión (agosto 2026)
#   REV = URL antigua PENDIENTE de confirmar (probablemente 404). El informe de
#         diagnóstico la marcará; pásame la ficha correcta y la actualizo.
# ---------------------------------------------------------------------------
STORES = [
    # ===================== SELLADORES =====================
    # --- Sika Sikaflex 11 FC Purform (estas 3 funcionan) ---
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

    # --- Bostik P795 Seal'N'Flex Premium ---  OK URL nueva (PrestaShop)
    {
        "store": "Diperplac BostikP795",
        "url": "https://diperplac.com/tienda/colas-masillas-y-siliconas/3850-bostik-masilla-poliuretano-p795-flex-300ml-blanca.html",
        "product": "BOSTIK_P795", "brand": "Bostik", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".current-price .price", "#our_price_display", ".price"],
    },

    # --- Bostik P360 / Seal N Flex ---  REV URL antigua a confirmar
    {
        "store": "Bricolemar BostikP360",
        "url": "https://www.bricolemar.com/adhesivos/bostik-seal-flex-p360.html",
        "product": "BOSTIK_P360", "brand": "Bostik", "category": "Selladores",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },

    # --- Soudal Soudaseal 240 FC ---  REV URL antigua a confirmar
    {
        "store": "Bricolemar Soudaseal",
        "url": "https://www.bricolemar.com/adhesivos/soudal-soudaseal-240-fc.html",
        "product": "SOUDAL_SOUDASEAL", "brand": "Soudal", "category": "Selladores",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },

    # --- Mapei Mapeflex PU45 ---  REV URL antigua a confirmar
    {
        "store": "Bricolemar MapeiPU45",
        "url": "https://www.bricolemar.com/adhesivos/mapei-mapeflex-pu45.html",
        "product": "MAPEI_PU45", "brand": "Mapei", "category": "Selladores",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },

    # ===================== ESPUMAS =====================
    # --- Sika Boom 180 (cánula) --- (funciona)
    {
        "store": "Ferrokey SikaBoom180",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-sikaboom-180-canula-750-ml",
        "product": "SIKABOOM_180", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 580 (pistola) ---  OK URL nueva (PrestaShop)
    {
        "store": "CriadoHermanos SikaBoom580",
        "url": "https://www.criadohermanos.com/index.php?id_product=30190&rewrite=espuma-de-poliuretano-sika-boom-580-750-cm3&controller=product",
        "product": "SIKABOOM_580", "brand": "Sika", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".current-price .price", "#our_price_display", ".price"],
    },

    # --- Sika Boom 151 Multiposition ---  OK URL nueva VERIFICADA (WooCommerce)
    {
        "store": "AzulejosMadrid SikaBoom151",
        "url": "https://azulejosmadridonline.es/producto/sika-boom-151-multiposicion-espuma-poliuretano-750ml/",
        "product": "SIKABOOM_151", "brand": "Sika", "category": "Espumas",
        "selectors": [".woocommerce-Price-amount", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 582 (tejas) ---  REV URL antigua a confirmar
    {
        "store": "Ferrokey SikaBoom582",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-sikaboom-582-tejas-750-ml",
        "product": "SIKABOOM_582", "brand": "Sika", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 584 (tejas) ---  OK URL nueva (Shopify, precio en JSON-LD)
    {
        "store": "Brikum SikaBoom584",
        "url": "https://www.brikum.com/products/cartucho-espuma-para-pegado-de-tejas-sika-boom-584-roof-tile-750ml-sika",
        "product": "SIKABOOM_584", "brand": "Sika", "category": "Espumas",
        "selectors": [".price__regular .price-item", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 420 Fire (ignífuga) ---  OK URL nueva (PrestaShop)
    {
        "store": "SuministrosGamesa SikaBoom420Fire",
        "url": "https://www.suministrosgamesa.com/mis-productos/1132863-sikaboom-420-fire-750cc-7612655073556.html",
        "product": "SIKABOOM_420_FIRE", "brand": "Sika", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".current-price .price", "#our_price_display", ".price"],
    },

    # --- Competidores ESPUMAS ---
    # Quilosa Orbafoam cánula  REV URL antigua a confirmar
    {
        "store": "Bricolemar Orbafoam Canula",
        "url": "https://www.bricolemar.com/espuma-poliuretano/1827-quilosa-orbafoam-espuma-poliuretano-750ml-canula.html",
        "product": "QUILOSA_ORBAFOAM_CAN", "brand": "Quilosa", "category": "Espumas",
        "selectors": ["#our_price_display", "[itemprop='price']", ".current-price .price", ".price"],
    },
    # Quilosa Orbafoam pistola (funciona)
    {
        "store": "Campollano Orbafoam Pistola",
        "url": "https://www.ferreteriacampollano.com/espuma-de-poliuretano-pistola-orbafoam-fijacion-60-750ml-quilosa.html",
        "product": "QUILOSA_ORBAFOAM_PIS", "brand": "Quilosa", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".product-price .price", ".price"],
    },
    # Soudal Soudafoam FR pistola (funciona)
    {
        "store": "Modrego Soudafoam FR Pistola",
        "url": "https://www.modregohogar.com/ferreteria/silicona/espumas-de-poliuretano/espuma-poliuretano-soudal-soudafoam-fr-pistola-750ml.html",
        "product": "SOUDAL_SOUDAFOAM_FR", "brand": "Soudal", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".product-price .price", ".price"],
    },
    # Soudal Soudafoam universal pistola  REV URL antigua a confirmar
    {
        "store": "Ferrokey Soudafoam Pistola",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-universal-pistola-soudal-750-ml",
        "product": "SOUDAL_SOUDAFOAM_PIS", "brand": "Soudal", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },
    # Penosil 123 pistola (funciona)
    {
        "store": "Ferrokey Penosil Pistola",
        "url": "https://www.ferrokey.eu/espuma-poliuretano-ultra-rapida-123-pistola-870-ml-penosil",
        "product": "PENOSIL_PISTOLA", "brand": "Penosil", "category": "Espumas",
        "selectors": [".product-info-price .price", "[itemprop='price']", ".price"],
    },
]


# ---------------------------------------------------------------------------
# Utilidades de extracción de precio
# ---------------------------------------------------------------------------
def _parse_price(text):
    """Extrae el primer número con formato de precio de un texto."""
    if text is None:
        return None
    text = str(text)
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})*,\d{2}|\d+[.,]\d{2}|\d+)", text)
    if not m:
        return None
    token = m.group(1)
    if "," in token:                       # formato europeo 1.234,56
        raw = token.replace(" ", "").replace(".", "").replace(",", ".")
    else:                                  # formato 12.95 o entero
        raw = token.replace(" ", "")
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _in_range(product, price):
    lo, hi = PRICE_RANGES.get(product, (0, 10_000))
    return price is not None and lo <= price <= hi


def _iter_jsonld_prices(soup):
    """Recorre todos los bloques JSON-LD y va devolviendo los precios que encuentre."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            try:  # algunos temas dejan comas finales; intentamos limpiar
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except Exception:
                continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in ("price", "lowPrice", "highPrice"):
                    if key in node:
                        p = _parse_price(node[key])
                        if p is not None:
                            yield p
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)


def _extract_price(entry, soup, html):
    """Devuelve (precio, metodo) probando varias estrategias en orden de fiabilidad."""
    product = entry["product"]

    # a) JSON-LD
    for p in _iter_jsonld_prices(soup):
        if _in_range(product, p):
            return p, "json-ld"

    # b) microdatos <meta itemprop=price content=...>
    for meta in soup.find_all("meta", attrs={"itemprop": "price"}):
        p = _parse_price(meta.get("content"))
        if _in_range(product, p):
            return p, "meta-itemprop"

    # c) selectores CSS de la entrada
    for sel in entry.get("selectors", []):
        for node in soup.select(sel):
            p = _parse_price(node.get("content") or node.get_text())
            if _in_range(product, p):
                return p, f"css:{sel}"

    # d) último recurso: menor precio dentro de rango en toda la página
    candidates = [_parse_price(tok) for tok in re.findall(r"\d+[.,]\d{2}", html)]
    candidates = [c for c in candidates if _in_range(product, c)]
    if candidates:
        return min(candidates), "fallback-min"

    return None, "sin-precio"


def scrape_store(entry, timeout=20):
    """Devuelve (precio|None, estado) para una tienda."""
    try:
        resp = requests.get(entry["url"], headers=HEADERS, timeout=timeout)
    except Exception as exc:
        return None, f"error-red ({type(exc).__name__})"

    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"

    soup = BeautifulSoup(resp.text, "html.parser")
    price, method = _extract_price(entry, soup, resp.text)
    if price is not None:
        return price, f"OK ({method})"
    return None, "sin precio en rango"


def scrape_all():
    """Rastrea todas las tiendas, imprime un informe y devuelve las filas con precio."""
    rows, report = [], []
    for entry in STORES:
        price, status = scrape_store(entry)
        report.append((entry["store"], entry["product"], status,
                       f"{price:.2f}" if price is not None else "—"))
        if price is not None:
            rows.append({
                "store": entry["store"],
                "product": entry["product"],
                "brand": entry["brand"],
                "category": entry["category"],
                "price": price,
            })
        time.sleep(random.uniform(1.0, 2.5))  # cortesía con las webs

    # -------- Informe de diagnóstico (se ve en el log de GitHub Actions) --------
    ok = sum(1 for r in report if r[2].startswith("OK"))
    print("\n" + "=" * 74)
    print(f"INFORME DE RASTREO — {ok}/{len(report)} tiendas con precio")
    print("=" * 74)
    print(f"{'':2}{'TIENDA':<32}{'PRODUCTO':<22}{'PRECIO':>8}  ESTADO")
    print("-" * 74)
    for store, product, status, price in report:
        flag = "  " if status.startswith("OK") else "! "
        print(f"{flag}{store:<32}{product:<22}{price:>8}  {status}")
    print("=" * 74)

    faltan = [r for r in report if not r[2].startswith("OK")]
    if faltan:
        print("\nTiendas SIN precio (revisar URL/selector):")
        for store, product, status, _ in faltan:
            print(f"   - {store} [{product}] -> {status}")
    print()

    return rows


if __name__ == "__main__":
    for r in scrape_all():
        print(r)
