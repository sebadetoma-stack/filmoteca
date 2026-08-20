"""
buscar_directores_youtube.py
Filmoteca Clásica — Buscar películas faltantes de directores famosos en YouTube

Lee directores_huecos.json, filtra los directores objetivo,
y busca cada película en YouTube via Search API.
Guarda resultados en buscar_directores_resultados.json (resumible).
No toca la DB.

Uso:
    $env:YT_API_KEY="tu_clave"
    python buscar_directores_youtube.py
    python buscar_directores_youtube.py --limite 50

Archivos:
    Entrada:  datos/directores_huecos.json
    Progreso: datos/buscar_directores_progreso.json
    Salida:   datos/buscar_directores_resultados.json
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse

# ── Argumentos ────────────────────────────────────────────────────────────────

LIMITE = None
if "--limite" in sys.argv:
    idx = sys.argv.index("--limite")
    try:
        LIMITE = int(sys.argv[idx + 1])
    except (IndexError, ValueError):
        print("ERROR: --limite requiere un número entero")
        sys.exit(1)

# ── Configuración ─────────────────────────────────────────────────────────────

BASE = r"C:\Users\sebad\Downloads\filmoteca\datos"
JSON_HUECOS   = os.path.join(BASE, "directores_huecos.json")
JSON_PROGRESO = os.path.join(BASE, "buscar_directores_progreso.json")
JSON_SALIDA   = os.path.join(BASE, "buscar_directores_resultados.json")

DIRECTORES_OBJETIVO = [
    "Ingmar Bergman",
    "Federico Fellini",
    "Akira Kurosawa",
    "Billy Wilder",
    "Alfred Hitchcock",
    "Stanley Kubrick",
    "François Truffaut",
    "Jean-Luc Godard",
    "Orson Welles",
    "Jean Renoir",
    "Vittorio De Sica",
    "Roberto Rossellini",
    "Michelangelo Antonioni",
    "Luis Buñuel",
    "Luchino Visconti",
    "Jean-Pierre Melville",
    "Robert Bresson",
    "Carl Theodor Dreyer",
    "Kenji Mizoguchi",
]

MAX_RESULTADOS   = 5    # resultados de YouTube por búsqueda
PAUSA_SEGUNDOS   = 0.3  # pausa entre llamadas para no martillar la API

# ── API Key ───────────────────────────────────────────────────────────────────

YT_KEY = os.environ.get("YT_API_KEY", "")
if not YT_KEY:
    print("ERROR: Falta YT_API_KEY")
    print("       $env:YT_API_KEY='tu_clave'")
    sys.exit(1)

# ── Helpers ───────────────────────────────────────────────────────────────────

def yt_search(query):
    """Busca en YouTube y devuelve lista de {video_id, titulo, canal, canal_id, descripcion}."""
    params = urllib.parse.urlencode({
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": MAX_RESULTADOS,
        "key": YT_KEY,
    })
    url = f"https://www.googleapis.com/youtube/v3/search?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        resultados = []
        for item in data.get("items", []):
            sn = item.get("snippet", {})
            resultados.append({
                "video_id":   item["id"]["videoId"],
                "titulo_yt":  sn.get("title", ""),
                "canal":      sn.get("channelTitle", ""),
                "canal_id":   sn.get("channelId", ""),
                "descripcion": sn.get("description", ""),
            })
        return resultados
    except Exception as e:
        print(f"    ERROR búsqueda: {e}")
        return []

def verificar_disponibilidad_ar(video_ids):
    """
    Verifica disponibilidad en Argentina de una lista de video_ids.
    Devuelve set de video_ids disponibles.
    Costo: 1 unidad por cada 50 videos.
    """
    disponibles = set()
    for i in range(0, len(video_ids), 50):
        lote = video_ids[i:i+50]
        ids_str = ",".join(lote)
        params = urllib.parse.urlencode({
            "part": "status,contentDetails",
            "id": ids_str,
            "regionCode": "AR",
            "key": YT_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/videos?{params}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
            for item in data.get("items", []):
                st = item.get("status", {})
                privacidad = st.get("privacyStatus", "")
                embeddable  = st.get("embeddable", False)
                upload_st   = st.get("uploadStatus", "")
                if privacidad == "public" and upload_st == "processed":
                    disponibles.add(item["id"])
        except Exception as e:
            print(f"    ERROR verificación AR: {e}")
    return disponibles

# ── Cargar huecos y armar lista ───────────────────────────────────────────────

if not os.path.exists(JSON_HUECOS):
    print(f"ERROR: No se encuentra {JSON_HUECOS}")
    sys.exit(1)

with open(JSON_HUECOS, encoding="utf-8") as f:
    huecos = json.load(f)

peliculas = []
for d in huecos:
    if d["director"] in DIRECTORES_OBJETIVO:
        for p in d["detalle_faltantes"]:
            peliculas.append({
                "tconst":   p["tconst"],
                "titulo":   p["titulo"],
                "anio":     p["anio"],
                "director": d["director"],
            })

print(f"Películas a buscar: {len(peliculas)}")
print(f"Cuota estimada: ~{len(peliculas) * 100:,} unidades de búsqueda")
print(f"Tiempo estimado: {len(peliculas) * PAUSA_SEGUNDOS / 60:.1f} min solo en pausas")
print()

# ── Cargar progreso previo ────────────────────────────────────────────────────

progreso = {}  # tconst -> resultado ya procesado
if os.path.exists(JSON_PROGRESO):
    with open(JSON_PROGRESO, encoding="utf-8") as f:
        progreso = json.load(f)
    print(f"Progreso previo: {len(progreso)} películas ya procesadas, retomando...")
else:
    print("Sin progreso previo, empezando desde cero.")
print()

# ── Buscar ────────────────────────────────────────────────────────────────────

pendientes = [p for p in peliculas if p["tconst"] not in progreso]
if LIMITE:
    pendientes = pendientes[:LIMITE]
    print(f"Pendientes (limitado a {LIMITE}): {len(pendientes)}")
else:
    print(f"Pendientes: {len(pendientes)}")
print()

for i, peli in enumerate(pendientes, 1):
    titulo = peli["titulo"]
    anio   = peli["anio"]
    tconst = peli["tconst"]

    query = f"{titulo} {anio} full movie"
    print(f"[{i}/{len(pendientes)}] {titulo} ({anio}) — {peli['director']}")
    print(f"    Buscando: {query!r}")

    resultados = yt_search(query)

    # Verificar disponibilidad AR de los candidatos
    video_ids = [r["video_id"] for r in resultados]
    disponibles_ar = set()
    if video_ids:
        disponibles_ar = verificar_disponibilidad_ar(video_ids)

    # Marcar cuáles están disponibles
    for r in resultados:
        r["disponible_ar"] = r["video_id"] in disponibles_ar

    candidatos_ar = [r for r in resultados if r["disponible_ar"]]

    print(f"    Encontrados: {len(resultados)} | Disponibles en AR: {len(candidatos_ar)}")
    if candidatos_ar:
        for c in candidatos_ar:
            print(f"      ✓ {c['video_id']} | {c['titulo_yt'][:60]} | {c['canal']}")

    # Guardar en progreso
    progreso[tconst] = {
        "tconst":      tconst,
        "titulo":      titulo,
        "anio":        anio,
        "director":    peli["director"],
        "query":       query,
        "resultados":  resultados,
        "candidatos_ar": candidatos_ar,
    }

    # Guardar progreso después de cada película
    with open(JSON_PROGRESO, "w", encoding="utf-8") as f:
        json.dump(progreso, f, ensure_ascii=False, indent=2)

    time.sleep(PAUSA_SEGUNDOS)

# ── Generar salida final ──────────────────────────────────────────────────────

print()
print("─" * 60)
print("Generando resumen final...")

resultados_finales = list(progreso.values())

# Estadísticas
con_candidatos = [r for r in resultados_finales if r["candidatos_ar"]]
sin_candidatos  = [r for r in resultados_finales if not r["candidatos_ar"]]

print(f"Total procesadas:        {len(resultados_finales)}")
print(f"Con candidato en AR:     {len(con_candidatos)}")
print(f"Sin candidato en AR:     {len(sin_candidatos)}")
print()

# Resumen por director
from collections import defaultdict
por_director = defaultdict(lambda: {"total": 0, "con_candidato": 0})
for r in resultados_finales:
    d = r["director"]
    por_director[d]["total"] += 1
    if r["candidatos_ar"]:
        por_director[d]["con_candidato"] += 1

print("Resumen por director:")
for director in DIRECTORES_OBJETIVO:
    if director in por_director:
        s = por_director[director]
        pct = s["con_candidato"] / s["total"] * 100 if s["total"] else 0
        print(f"  {director:<25} {s['con_candidato']:>3}/{s['total']:<3} con candidato ({pct:.0f}%)")

# Guardar salida
with open(JSON_SALIDA, "w", encoding="utf-8") as f:
    json.dump(resultados_finales, f, ensure_ascii=False, indent=2)

print()
print(f"Resultados guardados en: {JSON_SALIDA}")
print()
print("Siguiente paso: revisar candidatos con revisar_candidatos_directores.py")
