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

3) REGLAS OPCIONALES POR ENTRADA (nuevo, 2026-09-29). Una entrada de STORES puede
   llevar, además de "selectors":
       "text_regex": regex sobre el texto visible de la página; el grupo 1 es el
                     precio. Se prueba ANTES que los métodos genéricos. Sirve para
                     tiendas sin JSON-LD ni meta de precio, y para elegir el precio
                     CON IVA cuando la página muestra los dos.
       "strict":     True → no se usa el último recurso (d). Si el método específico
                     falla, la tienda sale como "sin precio" en el informe en vez de
                     guardar un número cualquiera de la página (p. ej. el precio sin IVA).

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
    # --- Selladores (cartucho 290-310 ml, NUNCA unipacs/salchichas de 600 ml) ---
    "SIKAFLEX_11FC":        (5, 35),
    "BOSTIK_P795":          (4, 30),
    "BOSTIK_P360":          (4, 25),
    "SOUDAL_SOUDASEAL":     (4, 25),
    "MAPEI_PU45":           (4, 25),
    "SOUDAL_SOUDAFLEX_40FC":(3, 20),   # rival Sikaflex-11FC (cartucho 300ml, Leroy Merlin lo etiqueta "450")
    # QUILOSA_PU50: en ManoMano (única fuente online encontrada con precio público) el
    # cartucho blanco de 300ml se vende de verdad a ~50€ (producto de nicho, poca
    # distribución en España, revendedor con margen alto). No es un precio erróneo:
    # ampliamos el rango para que deje de descartarse. 2026-09-23, decisión cliente.
    # 2026-09-29: Barral vende el mismo cartucho a 4,25 € (IVA incl.), así que los ~50 €
    # de ManoMano son de un revendedor caro y no el precio de mercado. Valorar dejar de
    # rastrear ManoMano o bajar el máximo del rango.
    "QUILOSA_PU50":         (3, 60),   # rival Sikaflex-11FC
    "FISCHER_PURFLEX":      (4, 25),   # rival Sikaflex-11FC (310ml). Antes (5, 25): Rationalstock llegó a 4,81 € con IVA
    "PENOSIL_TECNOPUR_P40": (4, 20),   # rival Sikaflex-11FC (equivalente a "PU-40 FC" de Penosil)
    "WURTH_PU40_PLUS":      (4, 25),   # rival Sikaflex-11FC (solo se usa si activas el bloque de Airtech más abajo)
    # --- Espumas (SOLO formato 750 ml) ---
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
    "SOUDAL_TEJAS":         (4, 22),   # rival Boom-584
    "PENOSIL_PISTOLA":      (5, 20),
    "PENOSIL_PU46_PISTOLA": (2, 18),   # rival Boom-580
    "PENOSIL_PU46_MANUAL":  (2, 18),   # rival Boom-180
    "FISCHER_PUP_PISTOLA":  (3, 25),   # rival Boom-580
    "FISCHER_PU_MANUAL":    (3, 22),   # rival Boom-180
    "FISCHER_PU_TEJAS":     (3, 22),   # rival Boom-584
    "CEYS_ESPUMAX_PISTOLA": (4, 22),   # Ceys Espumax Aislar y Rellenar Pistola 750 ml
    "CEYS_ESPUMAX_MANUAL":  (4, 22),   # Ceys Espumax Aislar y Rellenar Cánula 750 ml
    "CEYS_ESPUMAX_TEJAS":   (4, 22),   # Ceys Espumax Fijar y Montar Tejas Cánula 750 ml
    "WURTH_PURLOGIC_FLEX":  (5, 30),   # Würth PurLogic Flex 750 ml
    "WURTH_PU_TEJAS":       (4, 30),   # Würth PURLOGIC DUO Adhesivo Tejas 750 ml
    "PENOSIL_PU49":          (4, 20),   # Penosil PU-49 Tejas Pistola 750 ml
    "PENOSIL_EASYGUN_PU45":  (5, 22),   # Penosil Mega EasyGun PU-45 750 ml
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

    # --- Sika Boom 580 (pistola) ---  OK URL nueva VERIFICADA (paramireforma, PrestaShop)
    {
        "store": "ParaMiReforma SikaBoom580",
        "url": "https://paramireforma.com/espuma-poliuretano-sika-boom-580-fixfill-750cm3-p-3421.html",
        "product": "SIKABOOM_580", "brand": "Sika", "category": "Espumas",
        "selectors": [".current-price .price", "[itemprop='price']", ".price"],
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

    # --- Sika Boom 584 (tejas) ---  OK URL nueva VERIFICADA (paramireforma, 8,05 €)
    {
        "store": "ParaMiReforma SikaBoom584",
        "url": "https://paramireforma.com/espuma-poliuretano-sika-boom-584-roo-tejas-pistola-3432.html",
        "product": "SIKABOOM_584", "brand": "Sika", "category": "Espumas",
        "selectors": [".current-price .price", "[itemprop='price']", ".price"],
    },

    # --- Sika Boom 420 Fire (ignífuga) ---  candidato (PrestaShop) — lo confirmará el informe
    {
        "store": "PierreEtSol SikaBoom420Fire",
        "url": "https://www.pierreetsol.com/vente/es/espumas-de-poliuretano-sika/5910-sika-boom-420-fire-espuma-de-poliuretano-expandible-resistente-al-fuego-sika.html",
        "product": "SIKABOOM_420_FIRE", "brand": "Sika", "category": "Espumas",
        "selectors": [".current-price .price", "[itemprop='price']", ".price"],
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

    # ===================== NUEVOS RIVALES (petición cliente) =====================
    # --- Sikaflex-11FC: rivales en cartucho 290-310ml (NO unipacs 600ml) ---
    {
        "store": "LeroyMerlin Soudaflex40FC",
        "url": "https://www.leroymerlin.es/productos/construccion/impermeabilizacion-y-estanqueidad/adhesivos-siliconas-y-espumas-pu/selladores/masilla-de-poliuretano-450-soudaflex-300-ml-marron-82718586.html",
        "product": "SOUDAL_SOUDAFLEX_40FC", "brand": "Soudal", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".price", ".product-price"],
    },
    {
        # Precio real ~50€: producto de nicho con poca distribución en España, no un
        # error de scraping. Rango ampliado a (3, 60) en PRICE_RANGES (ver arriba).
        "store": "ManoMano QuilosaPU50",
        "url": "https://www.manomano.es/p/sintex-pu-50-alto-cr300-blanco-45609-643596",
        "product": "QUILOSA_PU50", "brand": "Quilosa", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".price"],
    },
    {
        # REV: ManoMano marca este anuncio como agotado y con precio anómalo (120€+).
        # Se mantiene en el listado para que el informe de diagnóstico lo señale, pero
        # no aportará dato mientras no se sustituya por una URL con stock/precio real.
        # (2026-09-29: ya hay una fuente fiable para este producto: Rationalstock, más abajo.)
        "store": "ManoMano FischerPurflex",
        "url": "https://www.manomano.es/p/masilla-poliuretano-blanco-bote-310ml-1907217",
        "product": "FISCHER_PURFLEX", "brand": "Fischer", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".price"],
    },
    {
        # REV: tienda multi-idioma (ruta /fr/) pero venta en España; confirmar precio tras primer rastreo
        "store": "LaTiendaElectricidad PenosilTecnopurP40",
        "url": "https://www.latiendadeelectricidad.com/fr/mastics/603596-mastic-polyurethane-tecnopur-p-40-300-ml-marron-penosil-8425589405107.html",
        "product": "PENOSIL_TECNOPUR_P40", "brand": "Penosil", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".price", "#our_price_display"],
    },

    # ---------- NUEVAS FUENTES (2026-09-29) ----------
    # Verificadas a mano: el precio aparece en el HTML sin login ni JavaScript.
    # OJO: robots.txt y términos de uso NO se han revisado; míralos antes de dejarlas
    # en producción. "strict": True evita que el último recurso (d) guarde el precio
    # sin IVA o el de otra variante como si fuera bueno.
    {
        # PrestaShop. Publica product:price:amount (4,25 € con IVA) y también
        # product:pretax_price:amount (3,51 € SIN IVA, y cae dentro del rango) → strict.
        "store": "Barral QuilosaPU50",
        "url": "https://www.barral.com/sellados/sintex-pu-50-300-ml-quilosa",
        "product": "QUILOSA_PU50", "brand": "Quilosa", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".current-price .price", ".price"],
        "strict": True,
    },
    {
        # Sin meta de precio. La tabla "Medidas disponibles" muestra
        # "4,3880 € 5,3095 € Iva incl." (sin IVA / con IVA): la regex coge el 2.º.
        # Blanco y gris de 310 ml cuestan lo mismo.
        "store": "Rationalstock FischerPurflex",
        "url": "https://www.rationalstock.es/catalogo/producto/fijacion/siliconas-y-selladores/selladores-para-materiales-porosos/sellador-de-poliuretano-fischer-purflex/20101000009",
        "product": "FISCHER_PURFLEX", "brand": "Fischer", "category": "Selladores",
        "text_regex": r"[\d.,]+\s*€\s*([\d.,]+)\s*€\s*Iva incl",
        "selectors": [],
        "strict": True,
    },
    {
        # PrestaShop. meta product:price:amount = 6,99 € (con IVA); el pretax (5,78 €)
        # también está en rango → strict. AGOTADO el 2026-09-29: el scraper no mira
        # stock, así que guardará el precio de lista aunque no haya unidades.
        "store": "BTIngenieros Soudaflex40FC",
        "url": "https://www.bt-ingenieros.com/adhesivos-y-selladores/6784-masilla-de-poliuretano-soudalflex-40fc-cartucho-300-ml-negro.html",
        "product": "SOUDAL_SOUDAFLEX_40FC", "brand": "Soudal", "category": "Selladores",
        "selectors": ["[itemprop='price']", ".current-price .price", ".price"],
        "strict": True,
    },
    {
        # Está listado como "Olivé PU-40 FC" (nombre anterior de Penosil en España).
        # Sin meta de precio: la tabla "Referencias disponibles" muestra
        # "Precio: 8,35€ 10,10€ Iva incluido" (sin IVA / con IVA); la regex coge el 2.º.
        # Blanco y marrón de 300 ml cuestan lo mismo.
        "store": "Boiract PenosilPU40FC",
        "url": "https://boiract.com/es/tienda/masilla-de-poliuretano-olive-pu-40-fc/1406",
        "product": "PENOSIL_TECNOPUR_P40", "brand": "Penosil", "category": "Selladores",
        "text_regex": r"[\d.,]+\s*€\s*([\d.,]+)\s*€\s*Iva incluido",
        "selectors": [],
        "strict": True,
    },

    # ---------- DESACTIVADAS (descomenta si te encajan) ----------
    # Combifit (NL), Soudaflex 40 FC 310 ml color madera. Precio en tabla de texto:
    # "1x €5.65". No sé si el precio lleva IVA ni si envía a España, y el resto del
    # monitor compara tiendas españolas.
    # {
    #     "store": "Combifit Soudaflex40FC",
    #     "url": "https://www.combifit.nl/en/soudal-soudaflex-40-fc-310-ml",
    #     "product": "SOUDAL_SOUDAFLEX_40FC", "brand": "Soudal", "category": "Selladores",
    #     "text_regex": r"1x\s*€\s*([\d.,]+)",
    #     "selectors": [],
    #     "strict": True,
    # },
    #
    # Airtech Online (FR), Würth Mastic PU 40 Plus blanco 300 ml. Tienda profesional
    # francesa: la página muestra 6,50 € HT y la meta product:price:amount 7,80 € (IVA
    # francés del 20 %). No es comparable con precios con IVA español (21 % → 7,87 €).
    # Es el único sitio que encontré con precio público de este producto.
    # {
    #     "store": "Airtech WurthPU40Plus",
    #     "url": "https://airtech-online.com/produit/mastic-colle-et-etanche-polyurethane-pu-40-plus-blanc-0892211300-wurth/",
    #     "product": "WURTH_PU40_PLUS", "brand": "Würth", "category": "Selladores",
    #     "selectors": [],
    #     "strict": True,
    # },

    # Nota: Würth Mastic PU 40 Plus queda FUERA del rastreo (wurth.es oculta el precio
    # hasta iniciar sesión; el único candidato con precio público es Airtech, arriba,
    # desactivado por la diferencia de IVA).

    # --- Espumas 750ml: rivales de Boom-580 (pistola), Boom-180 (manual) y Boom-584 (tejas) ---
    {
        "store": "LeroyMerlin SoudalProfoamPistola",
        "url": "https://www.leroymerlin.es/productos/espuma-de-poliuretano-soudal-profoam-750-ml-para-puertas-ventanas-y-paredes-en-color-amarillo-tiempo-de-secado-25-minutos-aplicacion-con-pistola-17668714.html",
        "product": "SOUDAL_SOUDAFOAM_PIS", "brand": "Soudal", "category": "Espumas",
        "selectors": [".price", "[itemprop='price']"],
    },
    {
        "store": "ManoMano SoudalProfoamManual",
        "url": "https://www.manomano.es/p/espuma-de-poliuretano-profoam-de-750ml-2631529",
        "product": "SOUDAL_SOUDAFOAM_CAN", "brand": "Soudal", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price"],
    },
    {
        "store": "LeroyMerlin SoudalTejas",
        "url": "https://www.leroymerlin.es/productos/espuma-de-poliuretano-soudafoam-tejas-tt-pistola-750-ml-81875136.html",
        "product": "SOUDAL_TEJAS", "brand": "Soudal", "category": "Espumas",
        "selectors": [".price", "[itemprop='price']"],
    },
    {
        "store": "LeroyMerlin FischerPUPPistola",
        "url": "https://www.leroymerlin.es/productos/pistola-fischer-espuma-poliuretano-pup-1k-750-84541566.html",
        "product": "FISCHER_PUP_PISTOLA", "brand": "Fischer", "category": "Espumas",
        "selectors": [".price", "[itemprop='price']"],
    },
    {
        "store": "LeroyMerlin FischerPUManual",
        "url": "https://www.leroymerlin.es/productos/espuma-de-poliuretano-expansiva-profesional-fischer-750-ml-manual-15355494.html",
        "product": "FISCHER_PU_MANUAL", "brand": "Fischer", "category": "Espumas",
        "selectors": [".price", "[itemprop='price']"],
    },
    {
        "store": "LeroyMerlin FischerPUTejas",
        "url": "https://www.leroymerlin.es/productos/espuma-de-poliuretano-expansiva-tejas-fischer-750-ml-pistola-15355522.html",
        "product": "FISCHER_PU_TEJAS", "brand": "Fischer", "category": "Espumas",
        "selectors": [".price", "[itemprop='price']"],
    },
    # Ceys Espumax Aislar y Rellenar: separar PISTOLA y MANUAL, ambos 750 ml.
    {
        "store": "GrupoIncera CeysEspumaxPistola",
        "url": "https://www.grupoincera.com/shop/ceys-085-espumax-pistola-aislar-y-rellenar-750-ml-ref-504803-47364",
        "product": "CEYS_ESPUMAX_PISTOLA", "brand": "Ceys", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".oe_price"],
    },
    {
        "store": "GrupoIncera CeysEspumaxManual",
        "url": "https://www.grupoincera.com/shop/ceys-068-espumax-manual-aislar-y-rellenar-750-ml-ref-504802-47362",
        "product": "CEYS_ESPUMAX_MANUAL", "brand": "Ceys", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".oe_price"],
    },
    {
        "store": "ManoMano PenosilPU46Pistola",
        "url": "https://www.manomano.es/p/espuma-poliuretano-pistola-pu46-750-ml-78235849",
        "product": "PENOSIL_PU46_PISTOLA", "brand": "Penosil", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price"],
    },
    {
        "store": "TiendaReco PenosilPU46Manual",
        "url": "https://tiendareco.com/ferreteria/productos-quimicos-pinturas-y-drogueria/colas-adhesivos-y-masillas/espuma-poliuretano-pu-46-manual-canula-750-ml-olive",
        "product": "PENOSIL_PU46_MANUAL", "brand": "Penosil", "category": "Espumas",
        "selectors": [".price", "[itemprop='price']"],
    },
    # ---------- Fuentes añadidas para completar las comparativas 750 ml ----------
    # Würth PurLogic Flex 750 ml — página oficial Würth España.
    {
        "store": "Wurth PurLogicFlex",
        "url": "https://www.wurth.es/espuma-pu-purlogic-flex-750ml",
        "product": "WURTH_PURLOGIC_FLEX", "brand": "Würth", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".product-price"],
        "strict": True,
    },
    # Penosil PU-49 Tejas Pistola 750 ml — fuente oficial Penosil España.
    {
        "store": "Penosil PU49 Pistola",
        "url": "https://penosil.com/es/producto/espuma-tejas-pistola-pu-49p-para-pegar-tejas/",
        "product": "PENOSIL_PU49", "brand": "Penosil", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".product-price"],
    },
    # Penosil Mega EasyGun PU-45 750 ml — fuente oficial Penosil España.
    {
        "store": "Penosil EasyGun PU45",
        "url": "https://penosil.com/es/producto/espuma-mega-easygun-pu-45-alto-rendimiento-2-en-1/",
        "product": "PENOSIL_EASYGUN_PU45", "brand": "Penosil", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".product-price"],
    },
    # Quilosa Orbafoam Pro Tejas 750 ml — Leroy Merlin.
    {
        "store": "LeroyMerlin Orbafoam Tejas",
        "url": "https://www.leroymerlin.es/productos/espuma-poliuretano-orbafoam-tejas-750ml-84406744.html",
        "product": "QUILOSA_ORBAFOAM_TEJ", "brand": "Quilosa", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".product-price"],
    },
    # Würth PURLOGIC DUO Adhesivo Tejas 750 ml — producto oficial de Würth España.
    # Se usa como la referencia Würth de espuma/adhesivo para tejas solicitada.
    {
        "store": "Wurth PurLogic Duo Tejas",
        "url": "https://www.wurth.es/purlogic-duo-adhesivo-tejas-750-ml",
        "product": "WURTH_PU_TEJAS", "brand": "Würth", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".product-price"],
        "strict": True,
    },
    # Ceys Espumax Fijar y Montar Tejas Cánula 750 ml.
    {
        "store": "SuministrosCallosa CeysEspumaxTejas",
        "url": "https://suministroscallosa.com/espuma-de-poliuretano-para-tejas-espumax/",
        "product": "CEYS_ESPUMAX_TEJAS", "brand": "Ceys", "category": "Espumas",
        "selectors": ["[itemprop='price']", ".price", ".product-price"],
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
    # ,\d{2,4}: acepta también "5,3095" (algunas tiendas muestran 4 decimales)
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})*,\d{2,4}|\d+[.,]\d{2}|\d+)", text)
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

    # 0) regla explícita de la entrada: regex sobre el texto visible (grupo 1 = precio)
    rx = entry.get("text_regex")
    if rx:
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        m = re.search(rx, text)
        if m:
            p = _parse_price(m.group(1))
            if _in_range(product, p):
                return p, "regex"

    # a) JSON-LD
    for p in _iter_jsonld_prices(soup):
        if _in_range(product, p):
            return p, "json-ld"

    # b) microdatos <meta itemprop=price content=...>
    for meta in soup.find_all("meta", attrs={"itemprop": "price"}):
        p = _parse_price(meta.get("content"))
        if _in_range(product, p):
            return p, "meta-itemprop"

    # b2) Open Graph de producto <meta property="product:price:amount"> (PrestaShop y otros)
    for prop in ("product:price:amount", "og:price:amount"):
        for meta in soup.find_all("meta", attrs={"property": prop}):
            p = _parse_price(meta.get("content"))
            if _in_range(product, p):
                return p, "meta-og-price"

    # c) selectores CSS de la entrada
    for sel in entry.get("selectors", []):
        for node in soup.select(sel):
            p = _parse_price(node.get("content") or node.get_text())
            if _in_range(product, p):
                return p, f"css:{sel}"

    # d) último recurso: menor precio dentro de rango en toda la página
    #    (se omite en entradas "strict": ahí es preferible "sin precio" a un número dudoso)
    if not entry.get("strict"):
        candidates = [_parse_price(tok) for tok in re.findall(r"\d+[.,]\d{2}", html)]
        candidates = [c for c in candidates if _in_range(product, c)]
        if candidates:
            return min(candidates), "fallback-min"

    return None, "sin-precio"


def scrape_store(entry, timeout=30, retries=2):
    """Devuelve (precio|None, estado) para una tienda. Reintenta si hay timeout/red."""
    last_err = "error-red"
    for intento in range(retries + 1):
        try:
            resp = requests.get(entry["url"], headers=HEADERS, timeout=timeout)
        except Exception as exc:
            last_err = f"error-red ({type(exc).__name__})"
            time.sleep(2 * (intento + 1))   # espera creciente antes de reintentar
            continue

        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"

        soup = BeautifulSoup(resp.text, "html.parser")
        price, method = _extract_price(entry, soup, resp.text)
        if price is not None:
            return price, f"OK ({method})"
        return None, "sin precio en rango"

    return None, last_err


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
