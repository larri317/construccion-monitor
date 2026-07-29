"""
notifier.py — Envío de notificaciones por email.

Versión temporal SIN envío real: solo informa por consola.
Mantiene la firma enviar_email(rows, alertas, force=False) para que
main.py funcione sin errores. Cuando quieras activar el email de
verdad, se reemplaza el cuerpo de esta función.
"""


def enviar_email(rows, alertas, force=False):
    """Notificación temporal: no envía correo, solo informa por consola."""
    if alertas:
        print(f"   [notifier] {len(alertas)} alerta(s) detectada(s) (email desactivado).")
    elif force:
        print("   [notifier] Resumen forzado, pero el email está desactivado.")
    else:
        print("   [notifier] Sin alertas. Nada que notificar.")
    print("   [notifier] (Envío de email desactivado por ahora.)")
