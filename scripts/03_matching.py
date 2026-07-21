#!/usr/bin/env python3
"""
Etapa 3: cruzar los videos cosechados contra el catálogo. CERO cuota: todo local.

Estrategia en dos pasos, porque comparar 20.000 videos contra 8.000 películas
son 160 millones de comparaciones difusas: demasiado lento.

  1. FILTRO BARATO por tokens: se indexan las películas por sus tokens de título.
     Para cada video, solo se consideran las películas que comparten al menos
     un token poco frecuente. Esto tira el 99,9% de los pares.
  2. SCORING CARO sobre los pocos candidatos que quedan.

Uso:  python3 03_matching.py [--reprocesar]
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone

from nucleo import (DUR_MINIMA_SEG, conectar, normalizar, puntuar,
                    tokens_clave)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reprocesar", action="store_true",
                    help="Borra coincidencias automáticas y rehace (respeta las humanas)")
    args = ap.parse_args()

    con = conectar()

    if args.reprocesar:
        n = con.execute(
            "DELETE FROM coincidencias WHERE revisado_por != 'humano' "
            "OR revisado_por IS NULL").rowcount
        con.commit()
        print(f"Borradas {n:,} coincidencias automáticas (las humanas quedan).\n")

    # ---------- índice invertido: token -> películas ----------
    print("Indexando catálogo...")
    pelis = {
        r["tconst"]: dict(r)
        for r in con.execute(
            "SELECT tconst, titulo_orig, titulo_primario, anio, duracion_min "
            "FROM peliculas")
    }
    # titulos_frase: solo inglés, español o sin idioma declarado.
    # Se usan para el match de frase (la señal más fuerte).
    # "La strada" en italiano NO debe matchear "Street Corner" en inglés.
    IDIOMAS_FRASE = {None, "en", "es", "es-419", "en-US", "en-GB"}
    titulos = defaultdict(list)       # todos los títulos (para score difuso)
    titulos_frase = defaultdict(list) # solo los de frase
    for r in con.execute("SELECT tconst, titulo, idioma FROM titulos_alt"):
        titulos[r["tconst"]].append(r["titulo"])
        if r["idioma"] in IDIOMAS_FRASE:
            titulos_frase[r["tconst"]].append(r["titulo"])

    indice = defaultdict(set)
    for tc, lista in titulos.items():
        for t in lista:
            for tok in tokens_clave(normalizar(t)):
                indice[tok].add(tc)

    # Los tokens muy frecuentes ("man", "love", "night") no discriminan nada
    # y hacen explotar el número de candidatos. Se ignoran como semilla.
    frecuentes = {t for t, s in indice.items() if len(s) > 300}
    print(f"  {len(pelis):,} películas, {len(indice):,} tokens "
          f"({len(frecuentes)} descartados por frecuentes)")

    # ---------- confianza por canal ----------
    conf = {r["channel_id"]: r["confianza"]
            for r in con.execute("SELECT channel_id, confianza FROM canales")}

    # Los canales con confianza 0 están excluidos: no generan coincidencias.
    excluidos = {cid for cid, c in conf.items() if c == 0}

    # Las decisiones humanas son sagradas: nunca se pisan.
    humanas = {(r["tconst"], r["video_id"]) for r in con.execute(
        "SELECT tconst, video_id FROM coincidencias WHERE revisado_por='humano'")}
    if humanas:
        print(f"  {len(humanas):,} decisiones humanas protegidas")
    if excluidos:
        print(f"  {len(excluidos)} canales excluidos (confianza 0)")

    # ---------- recorrer videos ----------
    if args.reprocesar:
        vids = con.execute(
            "SELECT video_id, channel_id, titulo, duracion_seg FROM videos "
            "WHERE activo = 1 AND duracion_seg >= ?", (DUR_MINIMA_SEG,)).fetchall()
    else:
        # Solo videos SIN ninguna coincidencia (nuevos)
        vids = con.execute("""
            SELECT v.video_id, v.channel_id, v.titulo, v.duracion_seg
            FROM videos v
            WHERE v.activo = 1
              AND v.duracion_seg >= ?
              AND NOT EXISTS (
                SELECT 1 FROM coincidencias co WHERE co.video_id = v.video_id
              )
        """, (DUR_MINIMA_SEG,)).fetchall()
    print(f"  {len(vids):,} videos de 55'+ a cruzar\n")

    filas, stats = [], defaultdict(int)
    ahora = datetime.now(timezone.utc).isoformat()

    for v in vids:
        if v["channel_id"] in excluidos:
            stats["canal_excluido"] += 1
            continue
        toks = tokens_clave(normalizar(v["titulo"], quitar_ruido=True))
        semillas = toks - frecuentes
        cand = set()
        for tok in (semillas or toks):
            cand |= indice.get(tok, set())
        if not cand:
            stats["sin_candidatos"] += 1
            continue

        vd = dict(v)
        mejor = None
        for tc in cand:
            r = puntuar(pelis[tc], vd, titulos[tc],
                    conf.get(v["channel_id"], 50),
                    titulos_frase[tc])
            if r["estado"] == "rechazada":
                continue
            if mejor is None or r["score"] > mejor[1]["score"]:
                mejor = (tc, r)

        if not mejor:
            stats["ninguno_pasa"] += 1
            continue

        tc, r = mejor
        if (tc, v["video_id"]) in humanas:
            stats["protegida"] += 1
            continue
        filas.append((tc, v["video_id"], r["score"], r["senales"],
                      r["estado"], "auto", ahora))
        stats[r["estado"]] += 1

    con.executemany(
        """INSERT OR REPLACE INTO coincidencias
           (tconst, video_id, score, senales, estado, revisado_por, creado)
           VALUES (?,?,?,?,?,?,?)""", filas)

    # El geobloqueo declarado por la API se propaga a la coincidencia.
    con.execute("""
        UPDATE coincidencias SET verificado_ar = CASE
            (SELECT ve_ar FROM videos v WHERE v.video_id = coincidencias.video_id)
            WHEN 1 THEN 'api_ok' WHEN 0 THEN 'bloqueado' ELSE 'sin_datos' END
        WHERE verificado_ar = 'sin_datos'""")
    con.commit()

    print("Resultado:")
    print(f"  confirmadas      {stats['confirmada']:>6,}")
    print(f"  pendientes       {stats['pendiente']:>6,}   <- revisión humana")
    print(f"  sin candidatos   {stats['sin_candidatos']:>6,}")
    print(f"  ninguno pasa     {stats['ninguno_pasa']:>6,}")
    if stats["protegida"]:
        print(f"  protegidas       {stats['protegida']:>6,}   (decisión humana previa)")
    if stats["canal_excluido"]:
        print(f"  canal excluido   {stats['canal_excluido']:>6,}")

    peliculas_ok = con.execute(
        "SELECT COUNT(DISTINCT tconst) FROM coincidencias "
        "WHERE estado='confirmada'").fetchone()[0]
    bloq = con.execute(
        "SELECT COUNT(DISTINCT tconst) FROM coincidencias "
        "WHERE estado='confirmada' AND verificado_ar='bloqueado'").fetchone()[0]
    print(f"\n  {peliculas_ok:,} películas distintas confirmadas")
    print(f"  ({bloq:,} de ellas bloqueadas en AR según la API)")
    con.close()


if __name__ == "__main__":
    main()
