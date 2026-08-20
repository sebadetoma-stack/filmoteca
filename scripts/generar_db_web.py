#!/usr/bin/env python3
"""
Genera filmoteca.db liviana (solo confirmadas) para el frontend.
La DB completa se copia como filmoteca_completa.db (backup en R2).

Uso: python scripts\generar_db_web.py
"""
import sqlite3
import shutil
import os
from pathlib import Path

BASE   = Path(__file__).resolve().parent.parent
DB_SRC = BASE / "datos" / "filmoteca_completa.db"
DB_WEB = BASE / "datos" / "filmoteca.db"

def main():
    if not DB_SRC.exists():
        print(f"No se encuentra {DB_SRC}")
        return

    # Crear DB web limpia
    if DB_WEB.exists():
        DB_WEB.unlink()

    src = sqlite3.connect(DB_SRC)
    dst = sqlite3.connect(DB_WEB)

    print("Generando filmoteca.db (solo confirmadas)...")

    # Obtener tconsts confirmados
    tconsts = {r[0] for r in src.execute(
        "SELECT DISTINCT tconst FROM coincidencias WHERE estado = 'confirmada'"
    )}
    print(f"  {len(tconsts):,} películas confirmadas")

    # Obtener video_ids confirmados
    video_ids = {r[0] for r in src.execute(
        "SELECT DISTINCT video_id FROM coincidencias WHERE estado = 'confirmada'"
    )}
    print(f"  {len(video_ids):,} videos confirmados")

    # Obtener channel_ids de esos videos
    channel_ids = {r[0] for r in src.execute(
        f"SELECT DISTINCT channel_id FROM videos WHERE video_id IN ({','.join('?'*len(video_ids))})",
        list(video_ids)
    )}

    # Obtener nconsts de personas de esas películas
    nconsts = {r[0] for r in src.execute(
        f"SELECT DISTINCT nconst FROM creditos WHERE tconst IN ({','.join('?'*len(tconsts))})",
        list(tconsts)
    )}
    print(f"  {len(nconsts):,} personas")

    # Copiar schema
    schema = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
    ).fetchall()
    for (sql,) in schema:
        try:
            dst.execute(sql)
        except Exception:
            pass
    dst.commit()

    # peliculas — solo confirmadas
    rows = src.execute(
        f"SELECT * FROM peliculas WHERE tconst IN ({','.join('?'*len(tconsts))})",
        list(tconsts)
    ).fetchall()
    dst.executemany(f"INSERT OR REPLACE INTO peliculas VALUES ({','.join('?'*len(rows[0]))})", rows)
    print(f"  peliculas: {len(rows):,}")

    # coincidencias — solo confirmadas
    rows = src.execute(
        "SELECT * FROM coincidencias WHERE estado = 'confirmada'"
    ).fetchall()
    dst.executemany(f"INSERT OR REPLACE INTO coincidencias VALUES ({','.join('?'*len(rows[0]))})", rows)
    print(f"  coincidencias: {len(rows):,}")

    # videos — solo los de confirmadas
    rows = src.execute(
        f"SELECT * FROM videos WHERE video_id IN ({','.join('?'*len(video_ids))})",
        list(video_ids)
    ).fetchall()
    dst.executemany(f"INSERT OR REPLACE INTO videos VALUES ({','.join('?'*len(rows[0]))})", rows)
    print(f"  videos: {len(rows):,}")

    # canales — solo los de esos videos
    rows = src.execute(
        f"SELECT * FROM canales WHERE channel_id IN ({','.join('?'*len(channel_ids))})",
        list(channel_ids)
    ).fetchall()
    dst.executemany(f"INSERT OR REPLACE INTO canales VALUES ({','.join('?'*len(rows[0]))})", rows)
    print(f"  canales: {len(rows):,}")

    # creditos — solo de confirmadas
    rows = src.execute(
        f"SELECT * FROM creditos WHERE tconst IN ({','.join('?'*len(tconsts))})",
        list(tconsts)
    ).fetchall()
    dst.executemany(f"INSERT OR REPLACE INTO creditos VALUES ({','.join('?'*len(rows[0]))})", rows)
    print(f"  creditos: {len(rows):,}")

    # personas — solo las de esas películas
    rows = src.execute(
        f"SELECT * FROM personas WHERE nconst IN ({','.join('?'*len(nconsts))})",
        list(nconsts)
    ).fetchall()
    dst.executemany(f"INSERT OR REPLACE INTO personas VALUES ({','.join('?'*len(rows[0]))})", rows)
    print(f"  personas: {len(rows):,}")

    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    src.close()

    size = DB_WEB.stat().st_size / 1024 / 1024
    size_orig = DB_SRC.stat().st_size / 1024 / 1024
    print(f"\nDB web: {size:.1f} MB (antes: {size_orig:.1f} MB)")
    print(f"Output: {DB_WEB}")
    # Actualizar fecha de modificación de filmoteca_completa.db
    import os, time
    now = time.time()
    os.utime(DB_SRC, (now, now))

    print(f"\nPróximos pasos:")
    print(f"  1. Subí filmoteca.db a R2 como 'filmoteca.db'")
    print(f"  2. Subí filmoteca_completa.db a R2 como 'filmoteca_completa.db' (backup)")

if __name__ == "__main__":
    main()
