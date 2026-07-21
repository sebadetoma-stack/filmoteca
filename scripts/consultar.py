#!/usr/bin/env python3
"""
Consultar la filmoteca. Cero cuota: todo local.

  python3 consultar.py --genero Film-Noir --decada 1940
  python3 consultar.py --actor "Richard Burton"
  python3 consultar.py --actor "Christopher Plummer" --solo-ar
  python3 consultar.py --director "Fritz Lang"
  python3 consultar.py --precode
  python3 consultar.py --genero Thriller --decada 1960 --min-rating 7
  python3 consultar.py --pendientes          # cola de revisión humana
  python3 consultar.py --resumen
  python3 consultar.py --exportar salida/filmoteca.csv
"""
import argparse
import csv
import sys

from nucleo import conectar


def construir(args):
    w, p = ["1=1"], []

    if not args.pendientes:
        w.append("estado = 'confirmada'")
    else:
        w.append("estado = 'pendiente'")

    if args.solo_ar:
        # Excluye lo que la API declara bloqueado en AR.
        # OJO: no captura restricciones de licencia (ej. Paramount Vault),
        # que la API no expone. Es un filtro necesario pero no suficiente.
        w.append("(verificado_ar != 'bloqueado')")
    if args.genero:
        w.append("generos LIKE ?"); p.append(f"%{args.genero}%")
    if args.decada:
        w.append("decada = ?"); p.append(args.decada)
    if args.anio:
        w.append("anio = ?"); p.append(args.anio)
    if args.desde:
        w.append("anio >= ?"); p.append(args.desde)
    if args.hasta:
        w.append("anio <= ?"); p.append(args.hasta)
    if args.precode:
        w.append("es_precode IN (1,2)")
    if args.min_rating:
        w.append("rating >= ?"); p.append(args.min_rating)
    if args.actor:
        w.append("reparto LIKE ?"); p.append(f"%{args.actor}%")
    if args.director:
        w.append("directores LIKE ?"); p.append(f"%{args.director}%")
    if args.titulo:
        w.append("(titulo LIKE ? OR titulo_orig LIKE ?)")
        p += [f"%{args.titulo}%"] * 2
    if args.idioma:
        w.append("idioma_audio LIKE ?"); p.append(f"{args.idioma}%")

    orden = {"rating": "rating DESC", "votos": "votos DESC",
             "anio": "anio", "score": "score DESC"}[args.orden]
    return f"SELECT * FROM filmoteca WHERE {' AND '.join(w)} ORDER BY {orden}", p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genero"); ap.add_argument("--decada", type=int)
    ap.add_argument("--anio", type=int); ap.add_argument("--desde", type=int)
    ap.add_argument("--hasta", type=int); ap.add_argument("--actor")
    ap.add_argument("--director"); ap.add_argument("--titulo")
    ap.add_argument("--idioma", help="es, en, ...")
    ap.add_argument("--min-rating", type=float)
    ap.add_argument("--precode", action="store_true")
    ap.add_argument("--solo-ar", action="store_true",
                    help="Excluir lo bloqueado en Argentina")
    ap.add_argument("--pendientes", action="store_true",
                    help="Cola de revisión: score alto pero algo no cierra")
    ap.add_argument("--orden", default="rating",
                    choices=["rating", "votos", "anio", "score"])
    ap.add_argument("--limite", type=int, default=40)
    ap.add_argument("--resumen", action="store_true")
    ap.add_argument("--exportar", metavar="ARCHIVO.csv")
    args = ap.parse_args()

    con = conectar()

    if args.resumen:
        print("Filmoteca — estado\n" + "=" * 62)
        for etq, q in [
            ("Películas en catálogo", "SELECT COUNT(*) FROM peliculas"),
            ("Videos cosechados", "SELECT COUNT(*) FROM videos WHERE activo=1"),
            ("Películas CONFIRMADAS",
             "SELECT COUNT(DISTINCT tconst) FROM coincidencias WHERE estado='confirmada'"),
            ("  ...visibles en AR",
             "SELECT COUNT(DISTINCT tconst) FROM coincidencias "
             "WHERE estado='confirmada' AND verificado_ar != 'bloqueado'"),
            ("Pendientes de revisión",
             "SELECT COUNT(*) FROM coincidencias WHERE estado='pendiente'"),
            ("Reportes sin atender",
             "SELECT COUNT(*) FROM reportes WHERE atendido=0"),
        ]:
            print(f"  {etq:<28} {con.execute(q).fetchone()[0]:>8,}")

        print("\nConfirmadas por década:")
        for d, c in con.execute(
            "SELECT decada, COUNT(DISTINCT tconst) FROM filmoteca "
            "WHERE estado='confirmada' GROUP BY decada ORDER BY decada"):
            print(f"  {d}s  {'█' * min(c // 5, 40)} {c:,}")

        print("\nPor canal:")
        for n, c in con.execute(
            "SELECT canal, COUNT(*) FROM filmoteca WHERE estado='confirmada' "
            "GROUP BY canal ORDER BY 2 DESC LIMIT 10"):
            print(f"  {(n or '(búsqueda)'):<42} {c:>5,}")
        return

    sql, params = construir(args)
    filas = con.execute(sql, params).fetchall()

    if args.exportar:
        with open(args.exportar, "w", newline="", encoding="utf-8") as f:
            if filas:
                w = csv.DictWriter(f, fieldnames=filas[0].keys())
                w.writeheader()
                w.writerows(dict(r) for r in filas)
        print(f"{len(filas):,} filas -> {args.exportar}")
        return

    if not filas:
        print("Sin resultados.")
        return

    print(f"{len(filas):,} resultados\n")
    for r in filas[:args.limite]:
        pc = " [PRE-CODE]" if r["es_precode"] == 1 else ""
        geo = "" if r["verificado_ar"] != "bloqueado" else "  ⚠ BLOQUEADA EN AR"
        print(f"{r['titulo']} ({r['anio']}){pc}{geo}")
        print(f"   {r['generos'] or '-'} · {r['duracion_min'] or '?'}min · "
              f"IMDb {r['rating'] or '-'} ({r['votos'] or 0:,} votos)")
        if r["directores"]:
            print(f"   dir: {r['directores']}")
        if r["reparto"]:
            print(f"   con: {r['reparto']}")
        print(f"   {r['url']}  [{r['yt_min']}min · {r['canal'] or '?'} · "
              f"score {r['score']:.0f}]")
        if args.pendientes:
            print(f"   señales: {con.execute(
                'SELECT senales FROM coincidencias WHERE video_id=?',
                (r['video_id'],)).fetchone()[0]}")
        print()

    if len(filas) > args.limite:
        print(f"... y {len(filas) - args.limite:,} más (--limite N)")
    con.close()


if __name__ == "__main__":
    main()
