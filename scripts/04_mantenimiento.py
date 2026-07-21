#!/usr/bin/env python3
"""
Etapa 4: mantenimiento. Dos mecanismos COMPLEMENTARIOS, no alternativos.

  A) BARRIDO (--barrido): detecta videos borrados/privados.
     videos.list con 50 IDs = 1 unidad. Si un video murió, NO vuelve en la
     respuesta: los IDs faltantes son los caídos.
     -> 500.000 videos verificables por día. Un catálogo de 20.000 cuesta
        400 unidades: el 4% de la cuota. Corrélo semanal sin pensarlo.

  B) REPORTES (--reportes): lo que la API NO puede ver y solo un humano detecta:
     película cortada, sin audio, imagen espejada para evadir Content ID,
     240p ilegible, o directamente otra película con el título cambiado.
     Acá el reporte del usuario es insustituible.

Y la reparación (--reparar): gasta el bucket de 100 búsquedas/día —que es
independiente del pool de 10.000— para buscarle reemplazo a lo caído.

Uso:
  python3 04_mantenimiento.py --barrido
  python3 04_mantenimiento.py --reportar VIDEO_ID --motivo incompleta
  python3 04_mantenimiento.py --reportes
  python3 04_mantenimiento.py --reparar
"""
import argparse
import os
import sys
from datetime import datetime, timezone

from nucleo import (Cuota, conectar, evaluar_region, iso_a_segundos, puntuar)

PAIS = os.environ.get("FILMOTECA_PAIS", "AR")

MOTIVOS = ["no_reproduce", "geobloqueado", "incompleta", "mala_calidad",
           "pelicula_equivocada", "sin_audio", "otro"]


def barrido(con, cuota):
    """Chequeo de existencia en lote. Baratísimo."""
    from _api import llamar  # helper compartido

    vids = [r["video_id"] for r in con.execute(
        "SELECT video_id FROM videos WHERE activo = 1")]
    print(f"Barriendo {len(vids):,} videos "
          f"({(len(vids) + 49) // 50:,} unidades de cuota)...")

    caidos, revisados, ahora = [], 0, datetime.now(timezone.utc).isoformat()
    for i in range(0, len(vids), 50):
        lote = vids[i:i + 50]
        d = llamar("videos", cuota, part="contentDetails,status",
                   id=",".join(lote), maxResults=50)
        if d is None:
            print("  [!] Cuota agotada. Reanudable: corré de nuevo mañana.")
            break

        vivos = {v["id"]: v for v in d.get("items", [])}
        for vid in lote:
            if vid not in vivos:
                caidos.append(vid)       # borrado o privado
            else:
                v = vivos[vid]
                rr = v["contentDetails"].get("regionRestriction", {})
                allowed = ",".join(rr.get("allowed", [])) or None
                blocked = ",".join(rr.get("blocked", [])) or None
                con.execute(
                    "UPDATE videos SET visto_ultima_vez=?, region_allowed=?, "
                    "region_blocked=?, ve_ar=? WHERE video_id=?",
                    (ahora, allowed, blocked,
                     evaluar_region(allowed, blocked, PAIS), vid))
            revisados += 1

    if caidos:
        con.executemany(
            "UPDATE videos SET activo=0, caido_desde=? WHERE video_id=?",
            [(ahora, v) for v in caidos])
    con.commit()

    print(f"  {revisados:,} revisados | {len(caidos):,} caídos")
    if caidos:
        # ¿Qué películas quedaron huérfanas? Esas son las que hay que rebuscar.
        huerfanas = con.execute("""
            SELECT COUNT(DISTINCT c.tconst) FROM coincidencias c
            WHERE c.estado='confirmada' AND NOT EXISTS (
              SELECT 1 FROM coincidencias c2 JOIN videos v ON v.video_id=c2.video_id
              WHERE c2.tconst=c.tconst AND c2.estado='confirmada' AND v.activo=1)
        """).fetchone()[0]
        print(f"  -> {huerfanas:,} películas sin ningún enlace vivo. "
              f"Corré --reparar.")
    print(f"  Cuota restante: {cuota.restante()}")


def reportar(con, video_id, motivo, detalle):
    if motivo not in MOTIVOS:
        sys.exit(f"Motivo inválido. Opciones: {', '.join(MOTIVOS)}")
    tc = con.execute(
        "SELECT tconst FROM coincidencias WHERE video_id=?", (video_id,)).fetchone()
    con.execute(
        "INSERT INTO reportes (video_id, tconst, motivo, detalle, fecha) "
        "VALUES (?,?,?,?,?)",
        (video_id, tc["tconst"] if tc else None, motivo, detalle,
         datetime.now(timezone.utc).isoformat()))

    # Un reporte de calidad degrada la coincidencia inmediatamente:
    # mejor un hueco honesto que un enlace que miente.
    if motivo in ("no_reproduce", "pelicula_equivocada"):
        con.execute("UPDATE coincidencias SET estado='rechazada', "
                    "revisado_por='humano' WHERE video_id=?", (video_id,))
        con.execute("UPDATE videos SET activo=0 WHERE video_id=?", (video_id,))
    elif motivo == "geobloqueado":
        con.execute("UPDATE coincidencias SET verificado_ar='bloqueado', "
                    "revisado_por='humano' WHERE video_id=?", (video_id,))
    elif motivo in ("incompleta", "sin_audio", "mala_calidad"):
        con.execute("UPDATE coincidencias SET estado='pendiente', "
                    "revisado_por='humano', notas=? WHERE video_id=?",
                    (f"reporte: {motivo}", video_id))
    con.commit()
    print(f"Reporte registrado para {video_id} ({motivo}).")


def ver_reportes(con):
    filas = con.execute("""
        SELECT r.id, r.motivo, r.detalle, r.fecha, v.titulo, p.titulo_primario, p.anio
        FROM reportes r
        LEFT JOIN videos v ON v.video_id = r.video_id
        LEFT JOIN peliculas p ON p.tconst = r.tconst
        WHERE r.atendido = 0 ORDER BY r.fecha DESC""").fetchall()
    if not filas:
        print("Sin reportes pendientes.")
        return
    print(f"{len(filas)} reportes pendientes:\n")
    for r in filas:
        peli = f"{r['titulo_primario']} ({r['anio']})" if r["titulo_primario"] else "?"
        print(f"  #{r['id']:<4} [{r['motivo']:<20}] {peli}")
        print(f"        video: {r['titulo'][:70] if r['titulo'] else '?'}")
        if r["detalle"]:
            print(f"        nota: {r['detalle']}")


def reparar(con, cuota):
    """
    Busca reemplazo para las películas confirmadas que se quedaron sin enlace vivo.
    Gasta del bucket de búsquedas (100/día), que NO toca el pool de 10.000.
    """
    from _api import llamar

    huerfanas = con.execute("""
        SELECT DISTINCT p.tconst, p.titulo_orig, p.titulo_primario,
               p.anio, p.duracion_min, p.votos
        FROM peliculas p JOIN coincidencias c ON c.tconst = p.tconst
        WHERE NOT EXISTS (
          SELECT 1 FROM coincidencias c2 JOIN videos v ON v.video_id = c2.video_id
          WHERE c2.tconst = p.tconst AND v.activo = 1 AND c2.estado != 'rechazada')
        ORDER BY p.votos DESC""").fetchall()

    disp = cuota.restante()["busquedas"]
    print(f"{len(huerfanas):,} películas sin enlace vivo. "
          f"Búsquedas disponibles hoy: {disp}\n")

    ahora = datetime.now(timezone.utc).isoformat()
    reparadas = 0

    for p in huerfanas[:disp]:
        titulos = [r["titulo"] for r in con.execute(
            "SELECT titulo FROM titulos_alt WHERE tconst=?", (p["tconst"],))]
        q = f'"{p["titulo_orig"]}" {p["anio"]} full movie'

        d = llamar("search", cuota, part="snippet", q=q, type="video",
                   videoDuration="long",   # >20min: filtra trailers sin costo extra
                   regionCode=PAIS, maxResults=10)
        if d is None:
            print("  [!] Bucket de búsquedas agotado. Seguí mañana.")
            break

        ids = [it["id"]["videoId"] for it in d.get("items", [])]
        if not ids:
            continue

        # 1 unidad del pool general para traer duraciones y geobloqueo
        det = llamar("videos", cuota, part="snippet,contentDetails",
                     id=",".join(ids), maxResults=50)
        if not det:
            break

        for v in det.get("items", []):
            cd, sn = v["contentDetails"], v["snippet"]
            seg = iso_a_segundos(cd.get("duration", ""))
            r = puntuar(dict(p), {"titulo": sn["title"], "duracion_seg": seg},
                        titulos, confianza_canal=40)  # canal desconocido: confianza baja
            if r["estado"] == "rechazada":
                continue

            rr = cd.get("regionRestriction", {})
            allowed = ",".join(rr.get("allowed", [])) or None
            blocked = ",".join(rr.get("blocked", [])) or None
            con.execute(
                """INSERT OR REPLACE INTO videos
                   (video_id, channel_id, titulo, duracion_seg, publicado,
                    idioma_audio, subtitulos, definicion, region_allowed,
                    region_blocked, ve_ar, activo, visto_ultima_vez)
                   VALUES (?,NULL,?,?,?,?,?,?,?,?,?,1,?)""",
                (v["id"], sn["title"], seg, sn.get("publishedAt"),
                 sn.get("defaultAudioLanguage"),
                 1 if cd.get("caption") == "true" else 0, cd.get("definition"),
                 allowed, blocked, evaluar_region(allowed, blocked, PAIS), ahora))
            con.execute(
                """INSERT OR REPLACE INTO coincidencias
                   (tconst, video_id, score, senales, estado, revisado_por, creado)
                   VALUES (?,?,?,?,?,'auto',?)""",
                (p["tconst"], v["id"], r["score"], r["senales"], r["estado"], ahora))
            reparadas += 1
            print(f"  [+] {p['titulo_primario']} ({p['anio']}) -> "
                  f"{r['estado']} {r['score']:.0f}")
            break   # el mejor alcanza

        con.commit()

    print(f"\n{reparadas} reparadas. Cuota: {cuota.restante()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--barrido", action="store_true")
    ap.add_argument("--reparar", action="store_true")
    ap.add_argument("--reportes", action="store_true")
    ap.add_argument("--reportar", metavar="VIDEO_ID")
    ap.add_argument("--motivo", choices=MOTIVOS)
    ap.add_argument("--detalle", default="")
    args = ap.parse_args()

    con = conectar()

    if args.reportar:
        reportar(con, args.reportar, args.motivo or "otro", args.detalle)
    elif args.reportes:
        ver_reportes(con)
    elif args.barrido or args.reparar:
        if not os.environ.get("YT_API_KEY"):
            sys.exit("Falta YT_API_KEY.")
        cuota = Cuota(con)
        if args.barrido:
            barrido(con, cuota)
        if args.reparar:
            reparar(con, cuota)
    else:
        ap.print_help()
    con.close()


if __name__ == "__main__":
    main()
