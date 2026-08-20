"""
ver_sin_poster_total.py
Muestra cuántas películas confirmadas no tienen poster ni sinopsis (toda la DB).
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

total = con.execute(
    "SELECT COUNT(DISTINCT tconst) FROM coincidencias WHERE estado = 'confirmada'"
).fetchone()[0]

sin_poster = con.execute("""
    SELECT COUNT(DISTINCT p.tconst) FROM peliculas p
    JOIN coincidencias co ON co.tconst = p.tconst
    WHERE co.estado = 'confirmada'
      AND p.poster_url IS NULL
""").fetchone()[0]

sin_sinopsis = con.execute("""
    SELECT COUNT(DISTINCT p.tconst) FROM peliculas p
    JOIN coincidencias co ON co.tconst = p.tconst
    WHERE co.estado = 'confirmada'
      AND p.sinopsis IS NULL
""").fetchone()[0]

print(f"Total confirmadas:  {total}")
print(f"Sin poster:         {sin_poster} ({sin_poster/total*100:.1f}%)")
print(f"Sin sinopsis:       {sin_sinopsis} ({sin_sinopsis/total*100:.1f}%)")

con.close()
