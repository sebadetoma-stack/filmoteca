#!/usr/bin/env python3
"""
Aplica a la base las decisiones tomadas en revision.html.

Uso:
  python3 aplicar_decisiones.py decisiones.json
"""
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: python3 aplicar_decisiones.py decisiones.json")

    ruta = Path(sys.argv[1])
    if not ruta.exists():
        sys.exit(f"No existe {ruta}")

    decisiones = json.loads(ruta.read_text(encoding="utf-8"))
    if not decisiones:
        sys.exit("El archivo no tiene decisiones.")

    con = sqlite3.connect(DB)

    aplicadas = 0
    for d in decisiones:
        cur = con.execute(
            """UPDATE coincidencias
               SET estado = ?, revisado_por = 'humano'
               WHERE tconst = ? AND video_id = ? AND estado = 'pendiente'""",
            (d["decision"], d["tconst"], d["video_id"]),
        )
        aplicadas += cur.rowcount

    con.commit()

    confirmadas = sum(1 for d in decisiones if d["decision"] == "confirmada")
    rechazadas = len(decisiones) - confirmadas
    total = con.execute(
        "SELECT COUNT(DISTINCT tconst) FROM coincidencias WHERE estado='confirmada'"
    ).fetchone()[0]
    quedan = con.execute(
        "SELECT COUNT(*) FROM coincidencias WHERE estado='pendiente'"
    ).fetchone()[0]
    con.close()

    # VACUUM fuera de la transacción
    con = sqlite3.connect(DB)
    con.execute("VACUUM")
    con.close()

    print(f"Aplicadas: {aplicadas} de {len(decisiones)} "
          f"({confirmadas} aprobadas, {rechazadas} rechazadas)")
    print(f"Películas confirmadas ahora: {total:,}")
    print(f"Pendientes que quedan: {quedan:,}")
    print("\nAcordate de copiar el filmoteca.db actualizado a filmoteca-web y hacer push.")


if __name__ == "__main__":
    main()
