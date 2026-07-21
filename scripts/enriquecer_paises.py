#!/usr/bin/env python3
"""
Obtiene el país de producción de cada película desde Wikidata
usando el tconst de IMDb (P345) y el país de origen (P495).

Sin API key, sin costo. Requiere internet.

Uso:
  python3 enriquecer_paises.py

Agrega una columna 'pais' a la tabla peliculas.
Para películas con más de un país, guarda los primeros dos separados por coma.
"""
import json, sqlite3, time, urllib.parse, urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
ENDPOINT = "https://query.wikidata.org/sparql"
LOTE = 80   # tconsts por consulta (conservador para evitar timeouts)
PAUSA = 65   # segundos entre consultas (Wikidata limita a 1 req/min durante outages)

HEADERS = {
    "User-Agent": "FilmotecaClasica/1.0 (educational project; contact via GitHub)",
    "Accept": "application/json",
}


def consultar_wikidata(tconsts: list[str]) -> dict[str, list[str]]:
    """
    Devuelve {tconst: [pais_en, ...]} para los tconsts del lote.
    """
    values = " ".join(f'"{t}"' for t in tconsts)
    query = f"""
SELECT ?imdbId (GROUP_CONCAT(DISTINCT ?countryLabel; SEPARATOR=",") AS ?paises)
WHERE {{
  VALUES ?imdbId {{ {values} }}
  ?film wdt:P345 ?imdbId ;
        wdt:P495 ?country .
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
    ?country rdfs:label ?countryLabel .
  }}
}}
GROUP BY ?imdbId
"""
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    url = f"{ENDPOINT}?{params}"
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        resultado = {}
        for row in data["results"]["bindings"]:
            tconst = row["imdbId"]["value"]
            paises = row["paises"]["value"].split(",")
            resultado[tconst] = paises[:2]  # máximo 2 países
        return resultado
    except Exception as e:
        print(f"  [!] Error en lote: {e}")
        return {}


def main():
    con = sqlite3.connect(DB)

    # Agregar columna si no existe
    cols = [r[1] for r in con.execute("PRAGMA table_info(peliculas)")]
    if "pais" not in cols:
        con.execute("ALTER TABLE peliculas ADD COLUMN pais TEXT")
        con.commit()
        print("Columna 'pais' agregada a la tabla peliculas")

    # Solo las películas confirmadas visibles en AR
    tconsts = [r[0] for r in con.execute("""
        SELECT DISTINCT p.tconst FROM peliculas p
        JOIN coincidencias co ON co.tconst = p.tconst
        JOIN videos v ON v.video_id = co.video_id
        WHERE co.estado = 'confirmada'
          AND v.activo = 1
          AND (co.verificado_ar != 'bloqueado' OR co.verificado_ar IS NULL)
          AND p.pais IS NULL
        ORDER BY p.votos DESC
    """)]
    print(f"{len(tconsts):,} películas sin país. Consultando Wikidata en lotes de {LOTE}...\n")

    total_encontradas = 0
    for i in range(0, len(tconsts), LOTE):
        lote = tconsts[i:i + LOTE]
        resultado = consultar_wikidata(lote)

        for tconst, paises in resultado.items():
            pais_str = ", ".join(paises)
            con.execute("UPDATE peliculas SET pais = ? WHERE tconst = ?",
                        (pais_str, tconst))
        con.commit()

        total_encontradas += len(resultado)
        pct = (i + len(lote)) / len(tconsts) * 100
        print(f"  Lote {i//LOTE + 1:>3}: {len(resultado):>3} encontradas "
              f"({total_encontradas:,} total) — {pct:.0f}% completado")
        time.sleep(PAUSA)

    # Estadísticas finales
    sin_pais = con.execute(
        "SELECT COUNT(*) FROM peliculas WHERE pais IS NULL").fetchone()[0]
    con_pais = con.execute(
        "SELECT COUNT(*) FROM peliculas WHERE pais IS NOT NULL").fetchone()[0]

    print(f"\nListo.")
    print(f"  Con país: {con_pais:,}")
    print(f"  Sin país: {sin_pais:,} (no están en Wikidata)")

    # Top países en las confirmadas
    print("\nTop países en películas confirmadas:")
    for pais, n in con.execute("""
        SELECT p.pais, COUNT(DISTINCT co.tconst)
        FROM coincidencias co JOIN peliculas p ON p.tconst = co.tconst
        WHERE co.estado = 'confirmada' AND p.pais IS NOT NULL
        GROUP BY p.pais ORDER BY 2 DESC LIMIT 15
    """):
        print(f"  {pais:<30} {n:>5}")

    con.close()


if __name__ == "__main__":
    main()
