"""
listar_pendientes.py
Lista las coincidencias pendientes con video_id para revisión manual.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

filas = con.execute("""
    SELECT p.titulo_primario, p.anio, v.video_id, p.duracion_min,
           v.duracion_seg, ca.nombre as canal
    FROM coincidencias co
    JOIN peliculas p ON p.tconst = co.tconst
    JOIN videos v ON v.video_id = co.video_id
    LEFT JOIN canales ca ON ca.channel_id = v.channel_id
    WHERE co.estado = 'pendiente' AND v.activo = 1
    ORDER BY p.titulo_primario
""").fetchall()

print(f"Total pendientes: {len(filas)}")
print()
for r in filas:
    dur_imdb = f"{r['duracion_min']}min" if r['duracion_min'] else "?"
    dur_yt = f"{r['duracion_seg']//60}min" if r['duracion_seg'] else "?"
    print(f"{r['titulo_primario']} ({r['anio']}) | IMDb:{dur_imdb} YT:{dur_yt} | https://youtube.com/watch?v={r['video_id']}")

con.close()
