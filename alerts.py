"""
alerts.py — Detecta variaciones de precio significativas.

Compara el precio de hoy de cada (tienda, producto) con la media de
los días anteriores. Si la variación supera UMBRAL (10% por defecto),
genera una alerta.
"""

from collections import defaultdict
from statistics import mean

UMBRAL = 0.10  # 10%


def detectar_alertas(historico, hoy_rows, umbral=UMBRAL):
    """
    historico : lista de dicts de database.read_all() (incluye días previos)
    hoy_rows  : lista de dicts del scraping de hoy (store, product, price...)
    Devuelve una lista de alertas (dicts).
    """
    # Precios previos por (store, product), excluyendo las fechas de hoy
    hoy_keys = {(r["store"], r["product"]) for r in hoy_rows}
    fechas_hoy = {r.get("date") for r in hoy_rows if r.get("date")}

    previos = defaultdict(list)
    for r in historico:
        if r.get("price") is None:
            continue
        if r.get("date") in fechas_hoy:
            continue
        key = (r.get("store"), r.get("product"))
        if key in hoy_keys:
            previos[key].append(r["price"])

    alertas = []
    for r in hoy_rows:
        key = (r["store"], r["product"])
        precios_previos = previos.get(key)
        if not precios_previos:
            continue  # sin histórico todavía para esta tienda/producto

        media = mean(precios_previos)
        if media == 0:
            continue

        variacion = (r["price"] - media) / media
        if abs(variacion) >= umbral:
            alertas.append({
                "store": r["store"],
                "product": r["product"],
                "brand": r.get("brand"),
                "category": r.get("category"),
                "precio_hoy": r["price"],
                "media_previa": round(media, 2),
                "variacion_pct": round(variacion * 100, 1),
                "tipo": "subida" if variacion > 0 else "bajada",
            })

    return alertas


if __name__ == "__main__":
    import database
    historico = database.read_all()
    print(f"{len(historico)} registros históricos cargados en total.")
