#!/usr/bin/env python3
"""
Agrega a la base las coincidencias revisadas de identificadas.json.

Antes de correr este script, abrí identificadas.json y:
  - Borrá las filas donde el candidato propuesto NO es correcto
  - Dejá solo las que confirmaste a mano

Uso:
  python3 agregar_coincidencias.py identificadas.json
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: python3 agregar_coincidencias.py identificadas.json")

    ruta = Path(sys.argv[1])
    entradas = json.loads(ruta.read_text(encoding="utf-8"))

    if not entradas:
        sys.exit("El archivo está vacío.")

    con = sqlite3.connect(DB)
    ahora = datetime.now(timezone.utc).isoformat()
    agregadas = 0

    for e in entradas:
        # Verificar que el video existe en la base
        v = con.execute(
            "SELECT video_id FROM videos WHERE video_id = ?", (e["video_id"],)
        ).fetchone()
        if not v:
            print(f"  [!] Video no encontrado en la base: {e['video_id']} — saltando")
            continue

        # Verificar que la película existe en el catálogo
        p = con.execute(
            "SELECT tconst FROM peliculas WHERE tconst = ?", (e["tconst"],)
        ).fetchone()
        if not p:
            print(f"  [!] tconst no encontrado: {e['tconst']} — saltando")
            continue

        con.execute("""
            INSERT OR REPLACE INTO coincidencias
            (tconst, video_id, score, senales, estado, revisado_por, creado)
            VALUES (?, ?, 95, '{"manual": true}', 'confirmada', 'humano', ?)
        """, (e["tconst"], e["video_id"], ahora))
        agregadas += 1
        print(f"  [+] {e['titulo_imdb']} ({e['anio_imdb']}) <- {e['titulo_video'][:50]}")

    con.commit()

    # VACUUM
    con.close()
    con = sqlite3.connect(DB)
    con.execute("VACUUM")
    con.close()

    total = sqlite3.connect(DB).execute(
        "SELECT COUNT(DISTINCT tconst) FROM coincidencias WHERE estado='confirmada'"
    ).fetchone()[0]

    print(f"\nAgregadas: {agregadas} de {len(entradas)}")
    print(f"Películas confirmadas ahora: {total:,}")
    print("\nAcordate de copiar el filmoteca.db a filmoteca-web y hacer push.")


if __name__ == "__main__":
    main()
