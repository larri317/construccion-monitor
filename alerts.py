"""
database.py — Lectura/escritura del histórico de precios en data/prices.csv.
El CSV se versiona dentro del propio repositorio (GitHub Actions hace commit).
"""

import os
import csv
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CSV_PATH = os.path.join(DATA_DIR, "prices.csv")
FIELDS = ["date", "store", "product", "brand", "category", "price"]


def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def append_rows(rows, day=None):
    """Añade las filas del día al CSV."""
    _ensure_file()
    day = day or date.today().isoformat()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        for r in rows:
            writer.writerow({
                "date": day,
                "store": r["store"],
                "product": r["product"],
                "brand": r["brand"],
                "category": r["category"],
                "price": f"{r['price']:.2f}",
            })


def read_all():
    """Devuelve todas las filas históricas como lista de dicts."""
    _ensure_file()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        try:
            r["price"] = float(r["price"])
        except (TypeError, ValueError):
            r["price"] = None
    return rows
