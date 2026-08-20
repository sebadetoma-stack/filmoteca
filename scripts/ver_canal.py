"""
ver_canal.py
Muestra estado de un canal en la DB: videos cosechados, coincidencias, etc.

Uso:
    python ver_canal.py UCO7swxrJsImdC1k5WsXxANA
    python ver_canal.py @ArtiflixMovies
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"

if len(sys.argv) < 2:
    print("Uso: python ver_canal.py <channel_id o handle>")
    sys.exit(1)

ident = sys.argv[1]

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

canal = con.execute(
    "SELECT * FROM canales WHERE channel_id=? OR handle=?",
    (ident, ident)
).fetchone()

if not canal:
    print(f"Canal no encontrado: {ident}")
    sys.exit(1)

print(f"Canal: {canal['nombre']}")
print(f"  ID:            {canal['channel_id']}")
print(f"  Handle:        {canal['handle']}")
print(f"  Confianza:     {canal['confianza']}")
print(f"  Última cosecha: {canal['ultima_cosecha'] or 'nunca'}")
print(f"  Total videos:  {canal['total_videos'] or 0}")
print()

# Videos en DB
total_videos = con.execute(
    "SELECT COUNT(*) FROM videos WHERE channel_id=?",
    (canal['channel_id'],)
).fetchone()[0]

largos = con.execute(
    "SELECT COUNT(*) FROM videos WHERE channel_id=? AND duracion_seg >= 3300",
    (canal['channel_id'],)
).fetchone()[0]

# Coincidencias
confirmadas = con.execute("""
    SELECT COUNT(*) FROM coincidencias co
    JOIN videos v ON v.video_id = co.video_id
    WHERE v.channel_id=? AND co.estado='confirmada'
""", (canal['channel_id'],)).fetchone()[0]

pendientes = con.execute("""
    SELECT COUNT(*) FROM coincidencias co
    JOIN videos v ON v.video_id = co.video_id
    WHERE v.channel_id=? AND co.estado='pendiente'
""", (canal['channel_id'],)).fetchone()[0]

rechazadas = con.execute("""
    SELECT COUNT(*) FROM coincidencias co
    JOIN videos v ON v.video_id = co.video_id
    WHERE v.channel_id=? AND co.estado='rechazada'
""", (canal['channel_id'],)).fetchone()[0]

print(f"Videos en DB:    {total_videos} ({largos} de 55'+)")
print(f"Coincidencias:")
print(f"  Confirmadas:   {confirmadas}")
print(f"  Pendientes:    {pendientes}")
print(f"  Rechazadas:    {rechazadas}")

con.close()
