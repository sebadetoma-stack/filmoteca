#!/usr/bin/env python3
"""
Audita las películas CONFIRMADAS con score bajo.
Las que la IA marca como no_match se rechazan directamente en la base.

Uso:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 ia_auditar.py --score 90
  python3 ia_auditar.py --score 100 --sin-frase   # solo las sin match de frase
"""
import argparse, json, os, sqlite3, sys, time, urllib.error, urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
API_URL = "https://api.anthropic.com/v1/messages"
MODELO = "claude-haiku-4-5-20251001"
MAX_TOKENS = 200

KEY = os.environ.get("ANTHROPIC_API_KEY")
if not KEY:
    sys.exit("Falta ANTHROPIC_API_KEY.")


def llamar_claude(prompt):
    body = json.dumps({
        "model": MODELO, "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": KEY, "anthropic-version": "2023-06-01",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["content"][0]["text"].strip()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", type=float, default=90,
                    help="Revisar confirmadas con score menor a este valor")
    ap.add_argument("--sin-frase", action="store_true",
                    help="Solo revisar las que no tienen match de frase (mas riesgosas)")
    ap.add_argument("--canal", action="append", default=[],
                    help="Solo revisar confirmadas de este canal (se puede repetir)")
    args = ap.parse_args()

    sin_frase_filtro = "AND (co.senales NOT LIKE '%frase\": true%')" if args.sin_frase else ""
    canal_filtro = ""
    if args.canal:
        nombres = " OR ".join("ca.nombre LIKE ?" for _ in args.canal)
        canal_filtro = f"AND ({nombres})"

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    sql = f"""
        SELECT co.tconst, co.video_id, co.score, co.senales,
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
        WHERE co.estado = 'confirmada'
          AND co.revisado_por != 'humano'
          AND co.score < ?
          AND v.activo = 1
          {sin_frase_filtro}
          {canal_filtro}
        GROUP BY co.tconst, co.video_id
        ORDER BY co.score ASC
    """

    params_sql = [args.score] + [f"%{c}%" for c in args.canal]
    filas = con.execute(sql, params_sql).fetchall()
    modo = " (solo sin frase)" if args.sin_frase else ""
    print(f"\n{len(filas)} confirmadas con score < {args.score}{modo} a auditar\n")

    rechazadas = []
    for i, r in enumerate(filas):
        descr = (r["descripcion"] or "")[:500]
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

        if decision == "no_match":
            rechazadas.append({
                "tconst": r["tconst"], "video_id": r["video_id"],
                "decision": "rechazada", "razon_ia": razon
            })

        marca = {"match": "✓", "no_match": "✗", "dudoso": "?"}.get(decision, "?")
        print(f"[{i+1:>4}/{len(filas)}] {marca} {r['titulo_primario'][:38]:<38} "
              f"score={r['score']:<5.0f} {decision:<10} {razon[:50]}")
        time.sleep(0.3)

    if rechazadas:
        for d in rechazadas:
            con.execute("""
                UPDATE coincidencias SET estado='rechazada', revisado_por='humano'
                WHERE tconst=? AND video_id=?
            """, (d["tconst"], d["video_id"]))
        con.commit()

    con.close()

    print(f"\nAuditadas: {len(filas)}")
    print(f"Rechazadas: {len(rechazadas)}")
    print(f"OK: {len(filas) - len(rechazadas)}")
    if rechazadas:
        print("\nAcordate de copiar el filmoteca.db a filmoteca-web y hacer push.")


if __name__ == "__main__":
    main()
