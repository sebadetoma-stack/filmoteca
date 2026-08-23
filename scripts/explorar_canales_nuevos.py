"""
explorar_canales_nuevos.py
Filmoteca Clásica — Explorar canales candidatos sin tocar la DB

Cosecha los videos de varios canales, filtra por duración (>=60 min),
cruza contra los tconst ya confirmados en filmoteca_completa.db,
y muestra un resumen comparativo para decidir cuáles agregar al pipeline.

No modifica nada — solo lectura. Guarda un JSON con los resultados.

Uso:
    $env:YT_API_KEY="tu_clave"
    python explorar_canales_nuevos.py
"""

import os
import sys
import json
import re
import sqlite3
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

# ── Configuración ─────────────────────────────────────────────────────────────

DB_PATH = r"C:\Users\sebad\Downloads\filmoteca\datos\filmoteca_completa.db"
OUT_PATH = Path(r"C:\Users\sebad\Downloads\filmoteca\datos\exploracion_canales.json")

# Canales a explorar: (handle_o_id, nota)
CANALES_CANDIDATOS = [
    ("@CrimeCoreMovies",   "sin nota"),
    ("@ActionCoded",       "sin nota"),
    ("@OfficialStreamCity","sin nota"),
    ("@CinemaCoded",       "CUIDADO: metadatos pueden ser incorrectos, verificar comentarios"),
    ("@ArmouredCarriers",  "sin nota"),
]

MIN_MINUTOS = 60  # Solo largometrajes

YT_KEY = os.environ.get("YT_API_KEY", "")
if not YT_KEY:
    print("ERROR: falta YT_API_KEY")
    print("       $env:YT_API_KEY='tu_clave'")
    sys.exit(1)

# ── Helpers YouTube API ────────────────────────────────────────────────────────

def api_get(endpoint, params, retries=3):
    params["key"] = YT_KEY
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urllib.parse.urlencode(params)
    for intento in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            if intento < retries - 1:
                time.sleep(2)
            else:
                raise e


def resolver_handle(handle_o_id):
    """Devuelve (channel_id, nombre) desde handle (@xxx) o channel ID (UCxxx)."""
    if handle_o_id.startswith("UC"):
        params = {"part": "snippet", "id": handle_o_id}
        data = api_get("channels", params)
        items = data.get("items", [])
        if not items:
            return None, None
        return handle_o_id, items[0]["snippet"]["title"]
    else:
        handle = handle_o_id.lstrip("@")
        params = {"part": "snippet", "forHandle": handle}
        data = api_get("channels", params)
        items = data.get("items", [])
        if not items:
            return None, None
        return items[0]["id"], items[0]["snippet"]["title"]


def obtener_uploads_id(channel_id):
    data = api_get("channels", {"part": "contentDetails", "id": channel_id})
    items = data.get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def paginar_video_ids(uploads_id):
    ids = []
    page_token = None
    while True:
        params = {"part": "contentDetails", "playlistId": uploads_id, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        data = api_get("playlistItems", params)
        for item in data.get("items", []):
            vid = item["contentDetails"].get("videoId")
            if vid:
                ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids


def iso8601_a_minutos(duracion):
    h = int((re.search(r'(\d+)H', duracion) or [0, 0])[1])
    m = int((re.search(r'(\d+)M', duracion) or [0, 0])[1])
    s = int((re.search(r'(\d+)S', duracion) or [0, 0])[1])
    return h * 60 + m + s // 60


def obtener_detalles(video_ids):
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        data = api_get("videos", {
            "part": "snippet,contentDetails,status",
            "id": ",".join(batch),
            "regionCode": "AR",
        })
        for item in data.get("items", []):
            minutos = iso8601_a_minutos(item["contentDetails"].get("duration", "PT0S"))
            videos.append({
                "video_id":    item["id"],
                "titulo":      item["snippet"]["title"],
                "descripcion": item["snippet"].get("description", "")[:300],
                "anio_subida": item["snippet"]["publishedAt"][:4],
                "minutos":     minutos,
                "embeddable":  item["status"].get("embeddable", True),
                "privacidad":  item["status"].get("privacyStatus", "public"),
            })
    return videos

# ── Cargar video_ids ya confirmados en la DB ───────────────────────────────────

def cargar_confirmados_db():
    """Devuelve un set de video_ids ya en coincidencias confirmadas."""
    if not Path(DB_PATH).exists():
        print(f"AVISO: DB no encontrada en {DB_PATH} — se omite cruce.")
        return set()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Auto-detectar tabla de coincidencias
    tablas = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    video_ids_db = set()
    if "coincidencias" in tablas:
        cols = {r[1] for r in cur.execute("PRAGMA table_info(coincidencias)").fetchall()}
        if "video_id" in cols and "estado" in cols:
            rows = cur.execute(
                "SELECT video_id FROM coincidencias WHERE estado='confirmada'"
            ).fetchall()
            video_ids_db = {r[0] for r in rows}
    con.close()
    return video_ids_db

# ── Pipeline principal ─────────────────────────────────────────────────────────

def explorar_canal(handle_o_id, nota, confirmados_db):
    print(f"\n{'='*60}")
    print(f"Explorando: {handle_o_id}")
    if nota != "sin nota":
        print(f"⚠️  NOTA: {nota}")
    print(f"{'='*60}")

    channel_id, nombre = resolver_handle(handle_o_id)
    if not channel_id:
        print(f"  ERROR: no se encontró el canal.")
        return None

    print(f"  Nombre: {nombre}")
    print(f"  ID:     {channel_id}")

    uploads_id = obtener_uploads_id(channel_id)
    if not uploads_id:
        print("  ERROR: no se pudo obtener la playlist de uploads.")
        return None

    print("  Paginando videos...")
    all_ids = paginar_video_ids(uploads_id)
    print(f"  Total videos en canal: {len(all_ids)}")

    print("  Obteniendo detalles...")
    todos = obtener_detalles(all_ids)

    largos = [v for v in todos if v["minutos"] >= MIN_MINUTOS and v["privacidad"] == "public"]
    ya_en_db = [v for v in largos if v["video_id"] in confirmados_db]
    nuevos = [v for v in largos if v["video_id"] not in confirmados_db]
    no_embeddable = [v for v in largos if not v["embeddable"]]

    print(f"\n  LARGOMETRAJES (≥{MIN_MINUTOS} min): {len(largos)}")
    print(f"  Ya en DB:                          {len(ya_en_db)}")
    print(f"  Potencialmente nuevos:             {len(nuevos)}")
    print(f"  No embeddables desde AR:           {len(no_embeddable)}")

    print(f"\n  {'─'*55}")
    print(f"  {'MIN':>4}  {'AÑO':>4}  TÍTULO")
    print(f"  {'─'*55}")
    for v in sorted(nuevos, key=lambda x: x["titulo"]):
        flag = " [no embed]" if not v["embeddable"] else ""
        ya = " [ya en DB]" if v["video_id"] in confirmados_db else ""
        print(f"  {v['minutos']:>4}  {v['anio_subida']:>4}  {v['titulo'][:60]}{flag}{ya}")

    return {
        "handle":           handle_o_id,
        "channel_id":       channel_id,
        "nombre":           nombre,
        "nota":             nota,
        "total_videos":     len(all_ids),
        "total_largos":     len(largos),
        "ya_en_db":         len(ya_en_db),
        "potencialmente_nuevos": len(nuevos),
        "no_embeddable":    len(no_embeddable),
        "videos_nuevos":    nuevos,
    }


def main():
    print("Filmoteca Clásica — Exploración de canales candidatos")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"\nCargando confirmados de la DB...")
    confirmados_db = cargar_confirmados_db()
    print(f"  {len(confirmados_db)} videos ya confirmados en DB.")

    resultados = []
    for handle, nota in CANALES_CANDIDATOS:
        try:
            res = explorar_canal(handle, nota, confirmados_db)
            if res:
                resultados.append(res)
        except Exception as e:
            print(f"\n  ERROR explorando {handle}: {e}")
        time.sleep(1)  # Pausa entre canales

    # ── Resumen comparativo ────────────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print("RESUMEN COMPARATIVO")
    print(f"{'='*60}")
    print(f"  {'CANAL':<28} {'TOTAL':>5} {'LARGOS':>6} {'NUEVOS':>6} {'NOTAS'}")
    print(f"  {'─'*28} {'─'*5} {'─'*6} {'─'*6} {'─'*20}")
    for r in resultados:
        nota_corta = "⚠️ metadatos dudosos" if r["nota"] != "sin nota" else ""
        print(f"  {r['nombre']:<28} {r['total_videos']:>5} {r['total_largos']:>6} "
              f"{r['potencialmente_nuevos']:>6}  {nota_corta}")

    # ── Guardar JSON ───────────────────────────────────────────────────────────
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"\nResultados guardados en: {OUT_PATH}")


if __name__ == "__main__":
    main()
