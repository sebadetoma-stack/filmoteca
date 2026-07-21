#!/usr/bin/env python3
"""
Etapa 2: cosecha de canales.

La idea central del proyecto: en vez de preguntar "¿dónde está esta película?"
(search.list, 100 búsquedas/día como techo), preguntamos "¿qué películas hay
en este canal?" (playlistItems.list, 1 unidad por cada 50 videos).

Un canal con 800 películas se enumera entero por 16 unidades.
Con 10.000 unidades por día se cosechan cientos de canales.

Uso:
  export YT_API_KEY=...
  python3 02_cosechar.py --semilla        # carga canales_semilla.csv y resuelve IDs
  python3 02_cosechar.py                  # cosecha todos los pendientes
  python3 02_cosechar.py --canal @PizzaFlix
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from nucleo import BASE, Cuota, conectar, evaluar_region, iso_a_segundos

from _api import llamar

KEY = os.environ.get("YT_API_KEY")
PAIS = os.environ.get("FILMOTECA_PAIS", "AR")


def cargar_semilla(con, cuota):
    """Lee el CSV y resuelve handles (@nombre) a channel IDs (UC...)."""
    import csv
    ruta = BASE / "datos" / "canales_semilla.csv"
    with open(ruta, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            ident = fila["identificador"].strip()
            if ident.startswith("UC"):
                params = {"id": ident}
            elif ident.startswith("@"):
                params = {"forHandle": ident}
            else:
                params = {"forUsername": ident}

            # channels.list cuesta 1 unidad y nos da el ID + la playlist de subidas
            d = llamar("channels", cuota, part="contentDetails,snippet", **params)
            if not d or not d.get("items"):
                print(f"  [?] No se resolvió: {ident}  ({fila['nombre']})")
                continue
            it = d["items"][0]
            cid = it["id"]
            uploads = it["contentDetails"]["relatedPlaylists"]["uploads"]
            con.execute(
                """INSERT OR REPLACE INTO canales
                   (channel_id, uploads_id, handle, nombre, capa, confianza, notas)
                   VALUES (?,?,?,?,?,?,?)""",
                (cid, uploads, ident if ident.startswith("@") else None,
                 fila["nombre"], fila["capa"], int(fila["confianza"]),
                 fila.get("notas", "")))
            print(f"  [ok] {fila['nombre']:<45} {cid}  uploads={uploads}")
    con.commit()


def cosechar_canal(con, cuota, canal):
    """Enumera TODAS las subidas del canal. 1 unidad por página de 50."""
    con.execute("PRAGMA foreign_keys = OFF")
    uploads = canal["uploads_id"]
    print(f"\n{canal['nombre']} ({canal['capa']})")

    ids, token, paginas = [], None, 0
    while True:
        p = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if token:
            p["pageToken"] = token
        d = llamar("playlistItems", cuota, **p)
        if not d:
            break
        for it in d.get("items", []):
            ids.append(it["contentDetails"]["videoId"])
        paginas += 1
        token = d.get("nextPageToken")
        if not token:
            break

    print(f"  {len(ids):,} videos listados ({paginas} unidades)")
    if not ids:
        return 0

    # Detalles en lotes de 50: 1 unidad por lote, sin importar cuántos campos.
    # Acá viene la duración Y el regionRestriction (geobloqueo) de una sola vez.
    guardados = 0
    for i in range(0, len(ids), 50):
        lote = ids[i:i + 50]
        d = llamar("videos", cuota, part="snippet,contentDetails",
                   id=",".join(lote), maxResults=50)
        if not d:
            break
        for v in d.get("items", []):
            cd, sn = v["contentDetails"], v["snippet"]
            rr = cd.get("regionRestriction", {})
            allowed = ",".join(rr.get("allowed", [])) or None
            blocked = ",".join(rr.get("blocked", [])) or None
            con.execute(
                """INSERT OR REPLACE INTO videos
                   (video_id, channel_id, titulo, descripcion, duracion_seg,
                    publicado, idioma_audio, subtitulos, definicion,
                    region_allowed, region_blocked, ve_ar, activo, visto_ultima_vez)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (v["id"], canal["channel_id"], sn["title"],
                 (sn.get("description") or "")[:2000],
                 iso_a_segundos(cd.get("duration", "")),
                 sn.get("publishedAt"), sn.get("defaultAudioLanguage"),
                 1 if cd.get("caption") == "true" else 0,
                 cd.get("definition"), allowed, blocked,
                 evaluar_region(allowed, blocked, PAIS),
                 datetime.now(timezone.utc).isoformat()))
            guardados += 1
    con.execute(
        "UPDATE canales SET ultima_cosecha=?, total_videos=? WHERE channel_id=?",
        (datetime.now(timezone.utc).isoformat(), guardados, canal["channel_id"]))
    con.commit()

    # ¿Cuántos son plausiblemente largometrajes?
    largos = con.execute(
        "SELECT COUNT(*) FROM videos WHERE channel_id=? AND duracion_seg >= 3300",
        (canal["channel_id"],)).fetchone()[0]
    bloq = con.execute(
        "SELECT COUNT(*) FROM videos WHERE channel_id=? AND ve_ar = 0",
        (canal["channel_id"],)).fetchone()[0]
    print(f"  {guardados:,} guardados | {largos:,} duran 55'+ | "
          f"{bloq:,} bloqueados en {PAIS} (según API)")
    return guardados


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semilla", action="store_true",
                    help="Cargar/resolver canales desde canales_semilla.csv")
    ap.add_argument("--canal", help="Cosechar solo este (handle o UC...)")
    args = ap.parse_args()

    if not KEY:
        sys.exit("Falta YT_API_KEY. export YT_API_KEY=tu_clave")

    con = conectar()
    cuota = Cuota(con)
    print(f"Cuota restante hoy: {cuota.restante()}\n")

    if args.semilla:
        cargar_semilla(con, cuota)
        print(f"\nCuota restante: {cuota.restante()}")
        return

    if args.canal:
        canales = con.execute(
            "SELECT * FROM canales WHERE handle=? OR channel_id=?",
            (args.canal, args.canal)).fetchall()
    else:
        # Los más confiables primero: si la cuota se corta, que se corte
        # en los canales que menos importan.
        canales = con.execute(
            "SELECT * FROM canales WHERE uploads_id IS NOT NULL "
            "ORDER BY confianza DESC").fetchall()

    if not canales:
        sys.exit("No hay canales. Corré primero: python3 02_cosechar.py --semilla")

    total = 0
    for c in canales:
        total += cosechar_canal(con, cuota, c)
        if cuota.restante()["unidades"] < 100:
            print("\n[!] Cuota casi agotada. Seguí mañana: el script es reanudable.")
            break

    print(f"\n{total:,} videos cosechados. Cuota restante: {cuota.restante()}")
    con.close()


if __name__ == "__main__":
    main()
