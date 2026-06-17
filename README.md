# 🏗️ Monitor de precios — Construcción

Agente automático que cada día rastrea los precios de **selladores y espumas de poliuretano** de Sika y su competencia, guarda el histórico, detecta subidas/bajadas y muestra todo en un dashboard web.

## Arquitectura

```
GitHub Actions (cron diario 08:00 Madrid)
        │
        ▼
   src/main.py
   ├── scraper.py    → extrae el precio de cada tienda
   ├── database.py   → guarda/lee data/prices.csv (en el propio repo)
   ├── alerts.py     → detecta variaciones ≥ 10%
   └── notifier.py   → envía email HTML con resumen + alertas
        │
        ▼
   dashboard.html    → lee el CSV y muestra KPIs y gráficos (GitHub Pages)
```

## Productos monitorizados

**Selladores PU**
- Sika · Sikaflex-11 FC Purform (Blanco, Gris, Marrón, Negro, Beige, Antracita)
- Competencia: Bostik P795 / P360 · Soudal Soudaseal · Mapei Mapeflex PU45

**Espumas PU**
- Sika · Sika Boom 180, 580, 151 Multiposition, 582, 584, 420 Fire
- Competencia: Quilosa Orbafoam · Soudal Soudafoam · Penosil 123

---

## Puesta en marcha

### 1. Crear el repositorio
En github.com → **New** → nombre `construccion-monitor` → **Private** → Create.
Sube todos los archivos (arrastrando desde el navegador o con `git push`).

### 2. Configurar el email (Gmail)
1. `myaccount.google.com/security` → activa la verificación en 2 pasos.
2. "Contraseñas de aplicaciones" → crea una nueva → copia los 16 caracteres.

### 3. Añadir los Secrets en GitHub
Repo → `Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Valor |
|---|---|
| `EMAIL_USER` | tu@gmail.com |
| `EMAIL_PASS` | los 16 caracteres de Google |
| `EMAIL_TO` | email donde recibir las alertas |

### 4. Configurar la URL del CSV en el dashboard
En `dashboard.html`, edita la línea `CSV_URL` y pon tu usuario/repo:
```js
const CSV_URL = "https://raw.githubusercontent.com/TU_USUARIO/construccion-monitor/main/data/prices.csv";
```

### 5. Activar GitHub Pages (web gratis)
Repo → `Settings → Pages` → Source: **Deploy from a branch** → Branch: **main** / **(root)** → Save.
Tu web quedará en:
```
https://TU_USUARIO.github.io/construccion-monitor/dashboard.html
```

### 6. Lanzar el primer rastreo
Repo → `Actions → Monitor Construccion → Run workflow`
(marca "Enviar email aunque no haya alertas" para recibir el resumen completo la primera vez).

---

## Añadir o cambiar tiendas
Edita el array `STORES` en `src/scraper.py`. Cada entrada:
```python
{
    "store": "Nombre Tienda Producto",
    "url": "https://tienda.com/pagina-del-producto",
    "product": "SIKAFLEX_11FC",        # clave de PRICE_RANGES
    "brand": "Sika", "category": "Selladores",
    "selectors": ["span.price", "[itemprop='price']", ".product-price"],
},
```
**Para encontrar el selector exacto:** abre la página en Chrome → clic derecho sobre el precio → "Inspeccionar" → copia la clase del elemento (`span.price`, etc.) y ponla la primera en la lista `selectors`.

Cada producto tiene un **rango de precio válido** en `PRICE_RANGES`. Si una tienda devuelve un número fuera de rango (precio de envío, otro producto…), se descarta automáticamente. Ajusta los rangos si conoces el precio real.
