#!/usr/bin/env python3
"""
Inserta en la DB las películas españolas aprobadas del JSON de revisión.
Lee espanolas_encontradas.json y procesa todas las que tienen
decision="pendiente_revision" (o sea, todas las que llegaron hasta acá).

Uso:
  python insertar_espanolas.py
"""
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB     = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
SALIDA = Path("espanolas_encontradas.json")

def evaluar_region(allowed, blocked, pais="AR"):
    if allowed:
        return 1 if pais in allowed.split(",") else 0
    if blocked:
        return 0 if pais in blocked.split(",") else 1
    return None


def main():
    datos = json.loads(SALIDA.read_text(encoding="utf-8"))
    con   = sqlite3.connect(DB)
    ahora = datetime.now(timezone.utc).isoformat()

    insertados = 0
    for d in datos:
        tconst   = d["tconst"]
        video_id = d["video_id"]

        # Verificar que no esté ya confirmada
        ya = con.execute(
            "SELECT 1 FROM coincidencias WHERE tconst=? AND estado='confirmada'",
            (tconst,)).fetchone()
        if ya:
            print(f"  [skip] {d['titulo']} — ya confirmada")
            continue

        ve_ar = evaluar_region(d.get("allowed"), d.get("blocked"))

        # Insertar video
        con.execute("""
            INSERT OR IGNORE INTO videos
            (video_id, channel_id, titulo, descripcion, duracion_seg,
             publicado, idioma_audio, subtitulos, definicion,
             region_allowed, region_blocked, ve_ar, activo, visto_ultima_vez)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)
        """, (video_id, d.get("channel_id") or None,
              d["vtitulo"], d.get("descripcion"), d.get("duracion_seg"),
              d.get("publicado"), d.get("idioma"), d.get("subtitulos", 0),
              d.get("definicion"), d.get("allowed"), d.get("blocked"),
              ve_ar, ahora))

        # Insertar coincidencia
        con.execute("""
            INSERT OR IGNORE INTO coincidencias
            (tconst, video_id, score, estado, revisado_por, notas, creado)
            VALUES (?, ?, 85.0, 'confirmada', 'humano',
                    'Búsqueda quirúrgica cine español clásico', ?)
        """, (tconst, video_id, ahora))

        print(f"  ✓ {d['titulo']} ({d['anio']}) — {d['canal']}")
        insertados += 1

    con.commit()
    con.close()

    print(f"\n{insertados} películas insertadas.")
    if insertados:
        print("Siguiente paso: enriquecer_tmdb.py → enriquecer_paises.py → pipeline de publicación.")


if __name__ == "__main__":
    main()
