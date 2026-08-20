"""
agregar_quirurgico.py
Agrega peliculas especificas a la DB sin pasar por el matcher.
Busca el tconst por titulo+anio, inserta en videos y coincidencias.

Uso:
    cd C:\\Users\\sebad\\Downloads\\filmoteca\\scripts\\
    $env:YT_API_KEY="tu_clave"
    python agregar_quirurgico.py
"""

import os
import re
import sqlite3
import requests
from datetime import datetime

DB_PATH    = r"C:\Users\sebad\Downloads\filmoteca\datos\filmoteca.db"
YT_API_KEY = os.environ.get("YT_API_KEY", "")

if not YT_API_KEY:
    print("ERROR: falta YT_API_KEY.")
    exit(1)

# Lista de peliculas a agregar: (titulo_busqueda, anio, video_id, canal_nombre)
PELICULAS = [
    ("The Furies",               1950, "7wZd_ssm3NM",  "BelenT89"),
    ("The Night Walker",         1964, "K5RYClikxcc",  "BelenT89"),
    ("The File on Thelma Jordon",1949, "MDn69cKtazQ",  "BelenT89"),
    ("The Other Love",           1947, "TBzynnihaGM",  "BelenT89"),
    ("You Belong to Me",         1941, "WPuOTlGA8j8",  "BelenT89"),
    ("Blowing Wild",             1953, "UOP14sTax-E",  "BelenT89"),
    ("Ball of Fire",             1941, "yrFGw4vj9d4",  "Samuel Goldwyn Films"),
    ("Trooper Hook",             1957, "M93LKFelTGo",  "FFF Full Free Films"),
    ("Golden Boy",               1939, "-oOBXnaKisc",  "vika khomyakova"),
    ("Titanic",                  1953, "PhVXYmwD2Ao",  "TJ DW"),
    ("Ten Cents a Dance",        1931, "uTuwVcFsCdY",  "Reel Classics"),
    ("The Plough and the Stars", 1936, "fyjvvzWffbw",  "fourscoreducats"),
    ("Escape to Burma",          1955, "ySXLb10uN3k",  "The Sprocket Vault"),
    ("Shopworn",                 1932, "V-yZtjkhAtE",  "Retro Reelworks"),
]

def obtener_detalle_video(video_id, api_key):
    """Obtiene titulo, duracion, canal y fecha de publicacion del video."""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,contentDetails,status",
        "id": video_id,
        "key": api_key,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item["snippet"]
        cd = item["contentDetails"]

        # Duracion ISO a segundos
        iso = cd.get("duration", "PT0S")
        h = int((re.search(r'(\d+)H', iso) or type('', (), {'group': lambda s, n: '0'})()).group(1) or 0)
        m = int((re.search(r'(\d+)M', iso) or type('', (), {'group': lambda s, n: '0'})()).group(1) or 0)
        s = int((re.search(r'(\d+)S', iso) or type('', (), {'group': lambda s, n: '0'})()).group(1) or 0)
        duracion_seg = h * 3600 + m * 60 + s

        return {
            "titulo":      snippet.get("title", ""),
            "channel_id":  snippet.get("channelId", ""),
            "canal_nombre":snippet.get("channelTitle", ""),
            "publicado":   snippet.get("publishedAt", "")[:10],
            "duracion_seg":duracion_seg,
            "definicion":  cd.get("definition", ""),
            "ve_ar":       1,  # asumimos visible, ya fue verificado
            "activo":      1,
        }
    except Exception as e:
        print(f"  ERROR obteniendo video {video_id}: {e}")
        return None

def buscar_tconst(titulo, anio, con):
    """Busca tconst en peliculas por titulo+anio."""
    patron = f"%{titulo[:20].lower()}%"
    cur = con.cursor()

    # Buscar exacto primero
    cur.execute("""
        SELECT tconst, titulo_orig FROM peliculas
        WHERE anio = ? AND LOWER(titulo_orig) LIKE ?
        LIMIT 5
    """, (anio, patron))
    rows = cur.fetchall()

    if not rows:
        # Intentar con titulo_primario
        cur.execute("""
            SELECT tconst, titulo_primario FROM peliculas
            WHERE anio = ? AND LOWER(titulo_primario) LIKE ?
            LIMIT 5
        """, (anio, patron))
        rows = cur.fetchall()

    return rows

def canal_id_por_nombre(nombre, con):
    """Busca channel_id en la tabla canales por nombre."""
    cur = con.cursor()
    cur.execute("SELECT channel_id FROM canales WHERE nombre LIKE ?", (f"%{nombre}%",))
    row = cur.fetchone()
    return row[0] if row else None

# ─── MAIN ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  Agregado quirurgico — {len(PELICULAS)} peliculas")
print(f"{'='*60}\n")

con = sqlite3.connect(DB_PATH)

agregadas   = []
no_encontradas = []
errores     = []

for titulo, anio, video_id, canal_nombre in PELICULAS:
    print(f"  Procesando: {titulo} ({anio})...")

    # 1. Buscar tconst
    candidatos = buscar_tconst(titulo, anio, con)
    if not candidatos:
        print(f"    [!] No encontrado en IMDb: '{titulo}' ({anio})")
        no_encontradas.append((titulo, anio, video_id))
        continue

    if len(candidatos) > 1:
        print(f"    [!] Multiples candidatos para '{titulo}' ({anio}):")
        for t, ttitulo in candidatos:
            print(f"        {t} — {ttitulo}")
        # Tomar el primero y avisar
        tconst, titulo_db = candidatos[0]
        print(f"    → Usando: {tconst} — {titulo_db}")
    else:
        tconst, titulo_db = candidatos[0]
        print(f"    → tconst: {tconst} — {titulo_db}")

    # 2. Obtener detalle del video desde YouTube
    detalle = obtener_detalle_video(video_id, YT_API_KEY)
    if not detalle:
        print(f"    [!] No se pudo obtener info del video {video_id}")
        errores.append((titulo, anio, video_id))
        continue

    # 3. Obtener channel_id
    channel_id = detalle["channel_id"]

    # Verificar si el canal está registrado, si no usar un placeholder
    cur = con.cursor()
    cur.execute("SELECT channel_id FROM canales WHERE channel_id = ?", (channel_id,))
    canal_existe = cur.fetchone()

    if not canal_existe:
        # Insertar canal mínimo
        con.execute("""
            INSERT OR IGNORE INTO canales (channel_id, nombre, capa, confianza, notas)
            VALUES (?, ?, 'particular', 50, 'Canal agregado quirurgicamente')
        """, (channel_id, detalle["canal_nombre"]))
        print(f"    → Canal nuevo registrado: {detalle['canal_nombre']} ({channel_id})")

    # 4. Insertar video
    try:
        con.execute("""
            INSERT OR IGNORE INTO videos
            (video_id, channel_id, titulo, duracion_seg, publicado, definicion, ve_ar, activo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id,
            channel_id,
            detalle["titulo"],
            detalle["duracion_seg"],
            detalle["publicado"],
            detalle["definicion"],
            detalle["ve_ar"],
            detalle["activo"],
        ))
    except Exception as e:
        print(f"    [!] Error insertando video: {e}")
        errores.append((titulo, anio, video_id))
        continue

    # 5. Insertar coincidencia como confirmada
    try:
        con.execute("""
            INSERT OR IGNORE INTO coincidencias
            (tconst, video_id, score, senales, estado, verificado_ar, revisado_por, notas, creado)
            VALUES (?, ?, 99, 'quirurgico', 'confirmada', 'ar_ok', 'humano', ?, ?)
        """, (
            tconst,
            video_id,
            f"Agregado manualmente desde playlist Stanwyck / canales one-shot",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        print(f"    [OK] Agregada: {titulo_db}")
        agregadas.append((titulo, anio, video_id, tconst))
    except Exception as e:
        print(f"    [!] Error insertando coincidencia: {e}")
        errores.append((titulo, anio, video_id))

con.commit()

# Verificar total
cur = con.cursor()
cur.execute("SELECT COUNT(DISTINCT tconst) FROM coincidencias WHERE estado = 'confirmada'")
total = cur.fetchone()[0]
con.close()

print(f"\n{'='*60}")
print(f"  RESULTADO")
print(f"{'='*60}")
print(f"  Agregadas OK:      {len(agregadas)}")
print(f"  No encontradas:    {len(no_encontradas)}")
print(f"  Errores:           {len(errores)}")
print(f"  Total confirmadas: {total}")

if no_encontradas:
    print(f"\n  NO ENCONTRADAS EN IMDB:")
    for t, a, vid in no_encontradas:
        print(f"    ({a}) {t} — https://youtube.com/watch?v={vid}")

if errores:
    print(f"\n  ERRORES:")
    for t, a, vid in errores:
        print(f"    ({a}) {t} — https://youtube.com/watch?v={vid}")

print("\n─── FIN ──────────────────────────────────────────────────")
