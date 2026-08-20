"""
exportar_sin_coincidencia.py
Filmoteca Clásica — Exporta videos de un canal sin ninguna coincidencia en la DB.

Uso:
    python exportar_sin_coincidencia.py UCO7swxrJsImdC1k5WsXxANA
    python exportar_sin_coincidencia.py @ArtiflixMovies

Salida: sin_identificar_<nombre_canal>.json
"""
import sqlite3
import sys
import json
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"

if len(sys.argv) < 2:
    print("Uso: python exportar_sin_coincidencia.py <channel_id o handle>")
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

filas = con.execute("""
    SELECT v.video_id, v.titulo, v.descripcion, v.duracion_seg,
           ca.nombre as canal
    FROM videos v
    JOIN canales ca ON ca.channel_id = v.channel_id
    WHERE v.channel_id = ?
      AND v.activo = 1
      AND v.duracion_seg >= 3300
      AND v.video_id NOT IN (
          SELECT video_id FROM coincidencias
      )
    ORDER BY v.titulo
""", (canal['channel_id'],)).fetchall()

print(f"Videos sin coincidencia (55'+): {len(filas)}")

videos = []
for r in filas:
    videos.append({
        "video_id":    r["video_id"],
        "titulo":      r["titulo"],
        "descripcion": r["descripcion"] or "",
        "duracion_seg": r["duracion_seg"],
        "canal":       r["canal"],
    })

nombre_archivo = f"sin_identificar_{canal['nombre'].replace(' ', '_').replace('/', '_')}.json"
salida = Path(__file__).resolve().parent.parent / "datos" / nombre_archivo

with open(salida, "w", encoding="utf-8") as f:
    json.dump(videos, f, ensure_ascii=False, indent=2)

print(f"Guardado en: {salida}")
print(f"Siguiente paso: python ia_resolver2.py --sin-id datos/{nombre_archivo}")

con.close()
