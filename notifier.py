"""
main.py — Orquestador del monitor de precios.

Flujo:
  1. Rastrea precios de todas las tiendas (scraper)
  2. Lee el histórico previo (database)
  3. Detecta alertas de variación (alerts)
  4. Guarda los precios de hoy en el CSV (database)
  5. Envía email (notifier) — siempre si hay alertas; con --force-email también sin ellas

Uso:
  python src/main.py                # corre y envía solo si hay alertas
  python src/main.py --force-email  # envía siempre el resumen diario
"""

import sys
from datetime import date

import scraper
import database
import alerts
import notifier


def main():
    force = "--force-email" in sys.argv
    hoy = date.today().isoformat()

    print(f"▶ Monitor de construcción — {hoy}")
    print("1) Rastreando tiendas...")
    rows = scraper.scrape_all()
    for r in rows:
        r["date"] = hoy
    print(f"   {len(rows)} precios recogidos.")

    print("2) Leyendo histórico...")
    historico = database.read_all()

    print("3) Detectando alertas...")
    alertas = alerts.detectar_alertas(historico, rows)
    print(f"   {len(alertas)} alerta(s).")

    print("4) Guardando precios de hoy...")
    database.append_rows(rows, day=hoy)

    print("5) Notificando...")
    notifier.enviar_email(rows, alertas, force=force)

    print("✔ Hecho.")


if __name__ == "__main__":
    main()
