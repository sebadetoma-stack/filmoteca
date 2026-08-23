#!/usr/bin/env python3
"""
Busca películas españolas clásicas en YouTube por título+año,
audita cada resultado con Claude (descripción, duración, canal incluidos),
y guarda los resultados a JSON para revisión humana.

NO toca la DB. El script de inserción es insertar_espanolas.py.

Canal baneado: YouTube Movies (UCgVM_a0rPEg_OCDUZ19mBSw) — es de pago.

Uso:
  $env:YT_API_KEY="..."
  $env:ANTHROPIC_API_KEY="..."
  python buscar_espanolas.py
"""
import json, os, re, sqlite3, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB      = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
YT_KEY  = os.environ.get("YT_API_KEY")
ANT_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not YT_KEY:  sys.exit("Falta YT_API_KEY")
if not ANT_KEY: sys.exit("Falta ANTHROPIC_API_KEY")

API_CLAUDE = "https://api.anthropic.com/v1/messages"
MODELO     = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300
SALIDA     = Path("espanolas_encontradas.json")

CANALES_BANEADOS = {"UCgVM_a0rPEg_OCDUZ19mBSw"}  # YouTube Movies (de pago)

PELICULAS = [
    # Berlanga
    ("tt0044706", "Bienvenido Mister Marshall", 1953),
    ("tt0047443", "Calabuch", 1956),
    ("tt0050709", "Los jueves milagro", 1957),
    ("tt0055166", "Plácido", 1961),
    ("tt0057166", "El verdugo", 1963),
    ("tt0072891", "La escopeta nacional", 1978),
    # Bardem
    ("tt0045556", "Cómicos", 1954),
    ("tt0046912", "Muerte de un ciclista", 1955),
    ("tt0049470", "Calle Mayor", 1956),
    ("tt0051783", "La venganza", 1958),
    ("tt0055739", "Nunca pasa nada", 1963),
    # Buñuel
    ("tt0042701", "Los olvidados", 1950),
    ("tt0044001", "Susana", 1951),
    ("tt0046346", "El", 1953),
    ("tt0047437", "Ensayo de un crimen", 1955),
    ("tt0053141", "Nazarín", 1959),
    ("tt0054452", "La joven", 1960),
    ("tt0057032", "El ángel exterminador", 1962),
    # Saura
    ("tt0056442", "Los golfos", 1960),
    ("tt0060282", "La caza", 1966),
    ("tt0063522", "Peppermint frappé", 1967),
    ("tt0065234", "La madriguera", 1969),
    ("tt0068228", "El jardín de las delicias", 1970),
    ("tt0071619", "La prima Angélica", 1974),
    ("tt0075247", "Cría cuervos", 1976),
    ("tt0077765", "Elisa, vida mía", 1977),
    # Ferreri
    ("tt0050490", "El pisito", 1958),
    ("tt0053604", "El cochecito", 1960),
    # Summers
    ("tt0057910", "Del rosa al amarillo", 1963),
    ("tt0059592", "La niña de luto", 1964),
    # Erice
    ("tt0071292", "El espíritu de la colmena", 1973),
    # Aranda
    ("tt0065800", "Las crueles", 1969),
    # Drove
    ("tt0069455", "Mi querida señorita", 1971),
    # Garci
    ("tt0076752", "Asignatura pendiente", 1977),
    # Fernán Gómez
    ("tt0058329", "El mundo sigue", 1963),
    # Borau
    ("tt0073785", "Furtivos", 1975),
]


def iso_a_segundos(d):
    if not d:
        return None
    h = int((re.search(r"(\d+)H", d) or [0, 0])[1])
    m = int((re.search(r"(\d+)M", d) or [0, 0])[1])
    s = int((re.search(r"(\d+)S", d) or [0, 0])[1])
    total = h * 3600 + m * 60 + s
    return total or None


def yt_get(endpoint, **params):
    params["key"] = YT_KEY
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [!] YouTube API error: {e}")
        return {}


def buscar_videos(titulo, anio):
    query = f"{titulo} {anio} película completa"
    data = yt_get("search", part="snippet", q=query, type="video",
                  videoDuration="long", maxResults=8)
    ids = []
    for item in data.get("items", []):
        vid      = item["id"].get("videoId", "")
        canal_id = item["snippet"].get("channelId", "")
        if vid and canal_id not in CANALES_BANEADOS:
            ids.append(vid)
        if len(ids) >= 5:
            break
    return ids


def obtener_metadata(video_ids):
    if not video_ids:
        return {}
    data = yt_get("videos", part="snippet,contentDetails",
                  id=",".join(video_ids), maxResults=50)
    resultado = {}
    for v in data.get("items", []):
        sn = v["snippet"]
        cd = v["contentDetails"]
        rr = cd.get("regionRestriction", {})
        resultado[v["id"]] = {
            "video_id":    v["id"],
            "channel_id":  sn.get("channelId", ""),
            "titulo":      sn.get("title", ""),
            "descripcion": (sn.get("description") or "")[:2000],
            "duracion_seg": iso_a_segundos(cd.get("duration", "")),
            "publicado":   sn.get("publishedAt"),
            "idioma":      sn.get("defaultAudioLanguage"),
            "subtitulos":  1 if cd.get("caption") == "true" else 0,
            "definicion":  cd.get("definition"),
            "allowed":     ",".join(rr.get("allowed", [])) or None,
            "blocked":     ",".join(rr.get("blocked", [])) or None,
        }
    return resultado


def obtener_nombre_canal(channel_id, con):
    if not channel_id:
        return "?"
    row = con.execute("SELECT nombre FROM canales WHERE channel_id = ?",
                      (channel_id,)).fetchone()
    if row:
        return row[0]
    data = yt_get("channels", part="snippet", id=channel_id)
    items = data.get("items", [])
    if items:
        return items[0]["snippet"].get("title", "?")
    return "?"


def auditar_con_claude(titulo_pelicula, anio, dur_imdb, directores, video, nombre_canal):
    dur_yt = f"{video['duracion_seg']//60} min" if video['duracion_seg'] else "?"
    descr  = (video["descripcion"] or "")[:600]

    prompt = f"""Sos un experto en cine clásico (1930-1979). Determiná si un video de YouTube es la película indicada.

PELÍCULA DEL CATÁLOGO:
- Título: {titulo_pelicula}
- Año: {anio}
- Duración IMDb: {dur_imdb}
- Director(es): {directores or '?'}

VIDEO EN YOUTUBE:
- Título: {video['titulo']}
- Canal: {nombre_canal}
- Duración: {dur_yt}
- Descripción: {descr if descr else '(sin descripción)'}

¿Este video es "{titulo_pelicula}" ({anio})?
Respondé SOLO con JSON:
{{"decision": "match"|"no_match"|"dudoso", "razon": "una línea"}}"""

    body = json.dumps({
        "model": MODELO, "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(API_CLAUDE, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": ANT_KEY,
        "anthropic-version": "2023-06-01",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            texto = json.loads(r.read())["content"][0]["text"].strip()
        i, f = texto.find("{"), texto.rfind("}") + 1
        if i >= 0 and f > i:
            return json.loads(texto[i:f])
    except Exception as e:
        print(f"  [!] Claude error: {e}")
    return {"decision": "dudoso", "razon": "error"}


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Ver cuáles ya están confirmadas en la DB
    confirmadas_previas = set()
    for tconst, _, _ in PELICULAS:
        row = con.execute(
            "SELECT 1 FROM coincidencias WHERE tconst=? AND estado='confirmada'",
            (tconst,)).fetchone()
        if row:
            confirmadas_previas.add(tconst)

    pendientes = [(t, titulo, anio) for t, titulo, anio in PELICULAS
                  if t not in confirmadas_previas]

    print(f"\n{len(confirmadas_previas)} ya confirmadas, {len(pendientes)} a buscar\n")
    print("─" * 70)

    resultados = []  # lo que se guarda al JSON

    for pelicula in pendientes:
        tconst, titulo, anio = pelicula
        print(f"\n[{titulo} ({anio})]")

        # Duración IMDb y directores desde la DB
        row = con.execute("""
            SELECT p.duracion_min,
                   GROUP_CONCAT(pe.nombre, ', ') as directores
            FROM peliculas p
            LEFT JOIN creditos cr ON cr.tconst = p.tconst AND cr.rol = 'director'
            LEFT JOIN personas pe ON pe.nconst = cr.nconst
            WHERE p.tconst = ?
            GROUP BY p.tconst
        """, (tconst,)).fetchone()
        dur_imdb   = f"{row['duracion_min']} min" if row and row['duracion_min'] else "?"
        directores = row['directores'] if row else "?"

        # Buscar en YouTube
        video_ids = buscar_videos(titulo, anio)
        if not video_ids:
            print("  Sin resultados en YouTube")
            time.sleep(1)
            continue

        # Metadata completa en una sola llamada
        metadata = obtener_metadata(video_ids)

        for vid_id in video_ids:
            video = metadata.get(vid_id)
            if not video:
                continue

            dur = video["duracion_seg"] or 0
            if dur < 3300:
                print(f"  ✗ {video['titulo'][:55]} — {dur//60}min (< 55min)")
                continue

            if video["channel_id"] in CANALES_BANEADOS:
                print(f"  ✗ {video['titulo'][:55]} — canal baneado")
                continue

            nombre_canal = obtener_nombre_canal(video["channel_id"], con)

            res      = auditar_con_claude(titulo, anio, dur_imdb, directores, video, nombre_canal)
            decision = res.get("decision", "dudoso")
            razon    = res.get("razon", "")

            marca = {"match": "✓", "no_match": "✗", "dudoso": "?"}.get(decision, "?")
            url   = f"https://www.youtube.com/watch?v={vid_id}"
            print(f"  {marca} [{nombre_canal}] {video['titulo'][:45]}")
            print(f"      {url}")
            print(f"      {razon[:70]}")

            if decision == "match":
                resultados.append({
                    "tconst":       tconst,
                    "titulo":       titulo,
                    "anio":         anio,
                    "video_id":     vid_id,
                    "url":          url,
                    "canal":        nombre_canal,
                    "channel_id":   video["channel_id"],
                    "vtitulo":      video["titulo"],
                    "duracion_seg": video["duracion_seg"],
                    "duracion_min": dur // 60,
                    "descripcion":  video["descripcion"],
                    "publicado":    video["publicado"],
                    "idioma":       video["idioma"],
                    "subtitulos":   video["subtitulos"],
                    "definicion":   video["definicion"],
                    "allowed":      video["allowed"],
                    "blocked":      video["blocked"],
                    "razon_ia":     razon,
                    "decision":     "pendiente_revision",  # vos decidís
                })
                print(f"      → Guardada para revisión")
                break  # un match por película alcanza

            time.sleep(0.4)

        time.sleep(1)

    con.close()

    # Guardar JSON
    SALIDA.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'─'*70}")
    print(f"Búsqueda finalizada.")
    print(f"  {len(resultados)} candidatas guardadas en {SALIDA}")
    print(f"  Revisá el JSON y corré insertar_espanolas.py con las que aprobés.")


if __name__ == "__main__":
    main()
