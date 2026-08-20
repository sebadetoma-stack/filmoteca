"""
ver_faltantes_detalle.py
Lista películas sin poster y sin sinopsis, indicando si están disponibles en AR.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

print("=== SIN POSTER ===")
filas = con.execute("""
    SELECT DISTINCT p.tconst, p.titulo_primario, p.anio, p.votos,
           MAX(CASE WHEN co.verificado_ar != 'bloqueado' THEN 1 ELSE 0 END) as en_ar
    FROM peliculas p
    JOIN coincidencias co ON co.tconst = p.tconst
    WHERE co.estado = 'confirmada'
      AND p.poster_url IS NULL
    GROUP BY p.tconst
    ORDER BY en_ar DESC, p.votos DESC NULLS LAST
""").fetchall()

print(f"Total: {len(filas)}")
print()
for r in filas:
    ar = "✓ en catálogo" if r['en_ar'] else "✗ bloqueada AR"
    print(f"  {ar} | {r['titulo_primario']} ({r['anio']}) | votos: {r['votos'] or 0}")

print()
print("=== SIN SINOPSIS ===")
filas2 = con.execute("""
    SELECT DISTINCT p.tconst, p.titulo_primario, p.anio, p.votos,
           MAX(CASE WHEN co.verificado_ar != 'bloqueado' THEN 1 ELSE 0 END) as en_ar
    FROM peliculas p
    JOIN coincidencias co ON co.tconst = p.tconst
    WHERE co.estado = 'confirmada'
      AND p.sinopsis IS NULL
    GROUP BY p.tconst
    ORDER BY en_ar DESC, p.votos DESC NULLS LAST
""").fetchall()

print(f"Total: {len(filas2)}")
print()
for r in filas2:
    ar = "✓ en catálogo" if r['en_ar'] else "✗ bloqueada AR"
    print(f"  {ar} | {r['titulo_primario']} ({r['anio']}) | votos: {r['votos'] or 0}")

con.close()
