"""
notifier.py — Envío de email HTML (resumen diario + alertas) por Gmail SMTP.
Lee las credenciales de variables de entorno (Secrets de GitHub):
  EMAIL_USER, EMAIL_PASS (App Password de 16 caracteres), EMAIL_TO
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
EMAIL_TO = os.environ.get("EMAIL_TO")


def _tabla_alertas(alertas):
    if not alertas:
        return "<p>Sin alertas de precio hoy. ✅</p>"
    filas = ""
    for a in alertas:
        flecha = "🔴 +" if a["subida"] else "🟢 "
        filas += (
            f"<tr>"
            f"<td>{a['brand']}</td>"
            f"<td>{a['product']}</td>"
            f"<td>{a['store']}</td>"
            f"<td>{a['precio_hoy']:.2f} €</td>"
            f"<td>{a['media_previa']:.2f} €</td>"
            f"<td>{flecha}{a['variacion_pct']:.1f} %</td>"
            f"</tr>"
        )
    return (
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse;font-family:Arial;font-size:13px'>"
        "<tr style='background:#FFD500'>"
        "<th>Marca</th><th>Producto</th><th>Tienda</th>"
        "<th>Hoy</th><th>Media previa</th><th>Variación</th></tr>"
        f"{filas}</table>"
    )


def _tabla_resumen(hoy_rows):
    if not hoy_rows:
        return "<p>No se han recogido precios hoy.</p>"
    filas = ""
    for r in sorted(hoy_rows, key=lambda x: (x["category"], x["product"])):
        filas += (
            f"<tr><td>{r['category']}</td><td>{r['brand']}</td>"
            f"<td>{r['product']}</td><td>{r['store']}</td>"
            f"<td>{r['price']:.2f} €</td></tr>"
        )
    return (
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse;font-family:Arial;font-size:13px'>"
        "<tr style='background:#222;color:#FFD500'>"
        "<th>Categoría</th><th>Marca</th><th>Producto</th>"
        "<th>Tienda</th><th>Precio</th></tr>"
        f"{filas}</table>"
    )


def enviar_email(hoy_rows, alertas, force=False):
    """Envía el email. Si no hay alertas y force=False, no envía nada."""
    if not (EMAIL_USER and EMAIL_PASS and EMAIL_TO):
        print("  ⚠ Faltan credenciales de email (EMAIL_USER/PASS/TO). No se envía.")
        return
    if not alertas and not force:
        print("  · Sin alertas y sin --force-email: no se envía email.")
        return

    hoy = date.today().isoformat()
    n = len(alertas)
    asunto = (f"🔴 [{n} alerta{'s' if n != 1 else ''}] · Monitor Construcción · {hoy}"
              if n else f"📊 Resumen diario · Monitor Construcción · {hoy}")

    html = f"""
    <div style="font-family:Arial;max-width:760px">
      <h2 style="color:#222">Monitor de precios — Construcción · {hoy}</h2>
      <h3 style="color:#c00">Alertas (variación ≥ 10%)</h3>
      {_tabla_alertas(alertas)}
      <h3 style="color:#222;margin-top:24px">Precios de hoy</h3>
      {_tabla_resumen(hoy_rows)}
      <p style="color:#888;font-size:12px;margin-top:20px">
        Email automático generado por el agente de monitorización.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())
    print(f"  ✓ Email enviado a {EMAIL_TO} ({asunto})")
