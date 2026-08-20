"""
buscar_sinopsis_wikipedia.py
Filmoteca Clásica — Busca sinopsis en Wikipedia para películas sin sinopsis.

Para cada película sin sinopsis visible en AR:
1. Busca en Wikipedia en español
2. Si no encuentra, busca en inglés y traduce con Claude

Uso:
    $env:ANTHROPIC_API_KEY="tu_clave"
    python buscar_sinopsis_wikipedia.py
"""

import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
API_URL = "https://api.anthropic.com/v1/messages"
PAUSA   = 2

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_KEY:
    print("ERROR: Falta ANTHROPIC_API_KEY")
    sys.exit(1)

def buscar_wikipedia(titulo, anio, lang="es"):
    """Busca la sinopsis de una película en Wikipedia."""
    # Primero buscar el artículo
    params = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": f"{titulo} {anio} film",
        "srlimit": 3,
        "format": "json",
    })
    url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FilmotecaClasica/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        resultados = data.get("query", {}).get("search", [])
        if not resultados:
            return None

        # Tomar el primer resultado y obtener el extracto
        pageid = resultados[0]["pageid"]
        params2 = urllib.parse.urlencode({
            "action": "query",
            "pageids": pageid,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "format": "json",
        })
        url2 = f"https://{lang}.wikipedia.org/w/api.php?{params2}"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "FilmotecaClasica/1.0"})
        with urllib.request.urlopen(req2, timeout=10) as r:
            data2 = json.loads(r.read())
        pages = data2.get("query", {}).get("pages", {})
        for page in pages.values():
            extracto = page.get("extract", "").strip()
            if extracto and len(extracto) > 50:
                # Tomar solo los primeros 500 caracteres
                return extracto[:500]
        return None
    except Exception as e:
        print(f"    ERROR Wikipedia ({lang}): {e}")
        return None

def traducir_con_claude(texto, titulo):
    """Traduce un texto al español usando Claude."""
    prompt = f"""Traducí al español argentino este fragmento de Wikipedia sobre la película "{titulo}". 
Devolvé SOLO la traducción, sin explicaciones ni comillas.

Texto en inglés:
{texto}"""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["content"][0]["text"].strip()
    except Exception as e:
        print(f"    ERROR Claude: {e}")
        return None

# ── Cargar películas sin sinopsis visibles en AR ──────────────────────────────

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

filas = con.execute("""
    SELECT DISTINCT p.tconst, p.titulo_primario, p.titulo_orig, p.anio
    FROM peliculas p
    JOIN coincidencias co ON co.tconst = p.tconst
    WHERE co.estado = 'confirmada'
      AND p.sinopsis IS NULL
      AND (co.verificado_ar != 'bloqueado' OR co.verificado_ar IS NULL)
    ORDER BY p.votos DESC NULLS LAST
""").fetchall()

print(f"Películas sin sinopsis a buscar: {len(filas)}")
print()

encontradas = 0
no_encontradas = []

for i, r in enumerate(filas, 1):
    tconst     = r["tconst"]
    titulo     = r["titulo_primario"]
    titulo_orig = r["titulo_orig"]
    anio       = r["anio"]

    print(f"[{i}/{len(filas)}] {titulo} ({anio})")

    # 1. Buscar en Wikipedia en español
    sinopsis = buscar_wikipedia(titulo, anio, lang="es")
    if not sinopsis and titulo_orig and titulo_orig != titulo:
        sinopsis = buscar_wikipedia(titulo_orig, anio, lang="es")

    if sinopsis:
        print(f"    ✓ encontrada en Wikipedia ES")
    else:
        # 2. Buscar en Wikipedia en inglés y traducir
        texto_en = buscar_wikipedia(titulo, anio, lang="en")
        if not texto_en and titulo_orig and titulo_orig != titulo:
            texto_en = buscar_wikipedia(titulo_orig, anio, lang="en")

        if texto_en:
            sinopsis = traducir_con_claude(texto_en, titulo)
            if sinopsis:
                print(f"    ✓ encontrada en Wikipedia EN y traducida")
            else:
                print(f"    ✗ traducción fallida")
        else:
            print(f"    ✗ no encontrada en Wikipedia")

    if sinopsis:
        con.execute(
            "UPDATE peliculas SET sinopsis=? WHERE tconst=?",
            (sinopsis[:500], tconst)
        )
        con.commit()
        encontradas += 1
    else:
        no_encontradas.append(f"{titulo} ({anio})")

    time.sleep(PAUSA)

con.close()

print()
print("─" * 60)
print(f"Encontradas: {encontradas}")
print(f"No encontradas: {len(no_encontradas)}")
if no_encontradas:
    print()
    for p in no_encontradas:
        print(f"  {p}")
