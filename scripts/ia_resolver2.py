#!/usr/bin/env python3
"""
Version 2: usa descripcion del video en TODOS los casos.

Para PENDIENTES: titulo + año + descripcion del video vs pelicula candidata.
Para SIN IDENTIFICAR: titulo + descripcion -> Claude extrae titulo/director/año
  para buscar manualmente en IMDb.

Uso:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 ia_resolver2.py --pendientes
  python3 ia_resolver2.py --sin-id sin_identificar.json
  python3 ia_resolver2.py --pendientes --sin-id sin_identificar.json
"""
import json, os, re, sqlite3, sys, time, urllib.error, urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
API_URL = "https://api.anthropic.com/v1/messages"
MODELO = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300

KEY = os.environ.get("ANTHROPIC_API_KEY")
if not KEY:
    sys.exit("Falta ANTHROPIC_API_KEY.")


def llamar_claude(prompt: str) -> str:
    body = json.dumps({
        "model": MODELO,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": KEY,
        "anthropic-version": "2023-06-01",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        print(f"  [!] HTTP {e.code}: {e.read().decode()[:200]}")
        return ""
    except Exception as e:
        print(f"  [!] Error: {e}")
        return ""


def parsear(texto):
    try:
        i, f = texto.find("{"), texto.rfind("}") + 1
        if i >= 0 and f > i:
            return json.loads(texto[i:f])
    except Exception:
        pass
    return {}


def resolver_pendientes(con):
    print("\n=== RESOLVIENDO PENDIENTES (con descripcion) ===\n")

    filas = con.execute("""
        SELECT co.tconst, co.video_id,
               p.titulo_primario, p.titulo_orig, p.anio, p.duracion_min,
               v.titulo as vtitulo, v.descripcion, v.duracion_seg,
               ca.nombre as canal,
               GROUP_CONCAT(pe.nombre, ', ') as directores
        FROM coincidencias co
        JOIN peliculas p ON p.tconst = co.tconst
        JOIN videos v ON v.video_id = co.video_id
        LEFT JOIN canales ca ON ca.channel_id = v.channel_id
        LEFT JOIN creditos cr ON cr.tconst = p.tconst AND cr.rol = 'director'
        LEFT JOIN personas pe ON pe.nconst = cr.nconst
        WHERE co.estado = 'pendiente'
          AND v.activo = 1
        GROUP BY co.tconst, co.video_id
        ORDER BY co.score DESC
    """).fetchall()

    print(f"{len(filas)} pendientes\n")
    decisiones = []

    for i, r in enumerate(filas):
        descr = (r["descripcion"] or "")[:600]
        dur_yt = f"{r['duracion_seg']//60} min" if r['duracion_seg'] else "?"
        dur_imdb = f"{r['duracion_min']} min" if r['duracion_min'] else "?"

        prompt = f"""Sos un experto en cine clásico (1930-1970). Determiná si un video de YouTube es la película indicada.

PELÍCULA DEL CATÁLOGO:
- Título: {r['titulo_primario']} / {r['titulo_orig']}
- Año: {r['anio']}
- Duración IMDb: {dur_imdb}
- Director(es): {r['directores'] or '?'}

VIDEO EN YOUTUBE:
- Título: {r['vtitulo']}
- Canal: {r['canal'] or '?'}
- Duración: {dur_yt}
- Descripción: {descr if descr else '(sin descripción)'}

¿Este video es "{r['titulo_primario']}" ({r['anio']})?
Respondé SOLO con JSON:
{{"decision": "match"|"no_match"|"dudoso", "razon": "una línea"}}"""

        resp = llamar_claude(prompt)
        res = parsear(resp)
        decision = res.get("decision", "dudoso")
        razon = res.get("razon", "")

        estado = {"match": "confirmada", "no_match": "rechazada"}.get(decision, "pendiente")
        if estado != "pendiente":
            decisiones.append({
                "tconst": r["tconst"], "video_id": r["video_id"],
                "decision": estado, "razon_ia": razon
            })

        marca = {"match": "✓", "no_match": "✗", "dudoso": "?"}.get(decision, "?")
        print(f"[{i+1:>3}/{len(filas)}] {marca} {r['titulo_primario'][:38]:<38} {decision:<10} {razon[:55]}")
        time.sleep(0.3)

    return decisiones


def resolver_sin_id(con, ruta):
    print("\n=== RESOLVIENDO SIN IDENTIFICAR (con descripcion) ===\n")

    videos = json.loads(Path(ruta).read_text(encoding="utf-8"))

    # Enriquecer con descripcion de la base
    for v in videos:
        row = con.execute(
            "SELECT descripcion FROM videos WHERE video_id = ?", (v["video_id"],)
        ).fetchone()
        v["descripcion"] = row["descripcion"] if row else ""

    print(f"{len(videos)} videos\n")
    para_buscar = []

    for i, v in enumerate(videos):
        descr = (v.get("descripcion") or "")[:600]
        dur = f"{v['duracion_seg']//60} min" if v.get('duracion_seg') else "?"

        prompt = f"""Sos un experto en cine clásico (1930-1970). Identificá la película de este video de YouTube.

VIDEO:
- Título: {v['titulo']}
- Canal: {v.get('canal','?')}
- Duración: {dur}
- Descripción: {descr if descr else '(sin descripción)'}

Identificá la película: título exacto, director y año de estreno.
Si es una serie de TV, episodio, o no podés identificarla con certeza, decí "no identificada".

Respondé SOLO con JSON:
{{"titulo": "título exacto", "director": "nombre", "anio": 1945, "confianza": "alta"|"media"|"baja", "razon": "una línea"}}"""

        resp = llamar_claude(prompt)
        res = parsear(resp)

        titulo = res.get("titulo", "")
        director = res.get("director", "")
        anio = res.get("anio", "")
        confianza = res.get("confianza", "baja")
        razon = res.get("razon", "")

        es_valida = (titulo and titulo.lower() != "no identificada"
                     and confianza in ("alta", "media")
                     and anio and 1928 <= int(anio) <= 1970)

        if es_valida:
            para_buscar.append({
                "video_id": v["video_id"],
                "titulo_video": v["titulo"],
                "duracion_seg": v.get("duracion_seg", 0),
                "canal": v.get("canal", ""),
                "titulo_pelicula": titulo,
                "director": director,
                "anio": anio,
                "confianza": confianza,
                "razon": razon
            })
            marca = "✓"
        else:
            marca = "✗"

        print(f"[{i+1:>2}/{len(videos)}] {marca} {v['titulo'][:45]:<45} -> {titulo[:30]} ({anio}) [{confianza}]")
        time.sleep(0.3)

    return para_buscar


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pendientes", action="store_true")
    ap.add_argument("--sin-id", metavar="ARCHIVO.json")
    args = ap.parse_args()

    if not args.pendientes and not args.sin_id:
        ap.print_help(); return

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    if args.pendientes:
        decisiones = resolver_pendientes(con)
        Path("ia_decisiones2.json").write_text(
            json.dumps(decisiones, indent=2, ensure_ascii=False), encoding="utf-8")
        conf = sum(1 for d in decisiones if d["decision"] == "confirmada")
        rech = sum(1 for d in decisiones if d["decision"] == "rechazada")
        print(f"\n{len(decisiones)} decisiones -> ia_decisiones2.json")
        print(f"  {conf} confirmadas, {rech} rechazadas")
        print(f"Aplicar: python3 aplicar_decisiones.py ia_decisiones2.json")

    if args.sin_id:
        para_buscar = resolver_sin_id(con, args.sin_id)
        Path("para_buscar_en_imdb.json").write_text(
            json.dumps(para_buscar, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n{len(para_buscar)} películas identificadas -> para_buscar_en_imdb.json")
        print("Próximo paso: buscar el tconst de cada una en https://www.imdb.com")
        print("y agregar al CSV o usar agregar_coincidencias.py")

    con.close()


if __name__ == "__main__":
    main()
