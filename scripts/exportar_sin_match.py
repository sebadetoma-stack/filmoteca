#!/usr/bin/env python3
"""
Exporta los videos que el matcher no pudo conectar con ninguna pelicula.
Son los "ninguno pasa" — videos de 55'+ en canales cosechados sin coincidencia.
"""
import json, sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# Videos activos de 55'+ que no tienen ninguna coincidencia (ni rechazada)
filas = con.execute("""
    SELECT v.video_id, v.titulo, v.duracion_seg, v.descripcion,
           ca.nombre as canal, ca.capa
    FROM videos v
    LEFT JOIN canales ca ON ca.channel_id = v.channel_id
    WHERE v.activo = 1
      AND v.duracion_seg >= 3300
      AND ca.confianza > 0
      AND NOT EXISTS (
          SELECT 1 FROM coincidencias co WHERE co.video_id = v.video_id
      )
    ORDER BY ca.confianza DESC, v.duracion_seg DESC
""").fetchall()

con.close()

resultado = [
    {
        "video_id": r["video_id"],
        "titulo": r["titulo"],
        "duracion_seg": r["duracion_seg"],
        "descripcion": (r["descripcion"] or "")[:600],
        "canal": r["canal"],
        "capa": r["capa"]
    }
    for r in filas
]

Path("sin_match.json").write_text(
    json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f"{len(resultado)} videos sin match exportados a sin_match.json")
