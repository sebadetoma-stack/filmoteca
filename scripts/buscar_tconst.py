#!/usr/bin/env python3
"""
Busca el tconst en los datasets de IMDb para las peliculas identificadas por la IA.
Cruza por titulo + año. No requiere red.

Uso:
  python3 buscar_tconst.py para_buscar_en_imdb.json
"""
import csv, gzip, json, re, sqlite3, sys, unicodedata
from pathlib import Path
from difflib import SequenceMatcher

IMDB = Path(__file__).resolve().parent.parent / "datos" / "imdb"
DB   = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"


def norm(s):
    if not s: return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def sim(a, b):
    return SequenceMatcher(None, a, b).ratio()


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: python3 buscar_tconst.py para_buscar_en_imdb.json")

    peliculas = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    # Filtrar TV y seriales antes de procesar
    tv_kw = ['TV-', 'TV ', 'teleplay', 'serial', 'episode', 'CHAPTER', 'CLIFFHANGER', 'MARATHON']
    peliculas = [p for p in peliculas
                 if not any(k in p['titulo_video'] for k in tv_kw)
                 or p['duracion_seg'] <= 7200]

    # Deduplicar por titulo+año
    from collections import defaultdict
    grupos = defaultdict(list)
    for p in peliculas:
        grupos[(p['titulo_pelicula'], p['anio'])].append(p)
    peliculas = [max(g, key=lambda x: x['duracion_seg']) for g in grupos.values()]

    print(f"Buscando tconst para {len(peliculas)} películas en IMDb...\n")

    # Cargar title.basics completo en memoria (filtrado por tipo movie)
    print("Cargando title.basics...")
    titulos = {}  # tconst -> (titulo_norm, anio)
    p_basics = IMDB / "title.basics.tsv.gz"
    with gzip.open(p_basics, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["titleType"] not in ("movie", "short", "tvMovie"):
                continue
            try:
                anio = int(r["startYear"])
            except ValueError:
                continue
            titulos[r["tconst"]] = {
                "titulo_orig": r["originalTitle"],
                "titulo_prim": r["primaryTitle"],
                "anio": anio,
                "norm_orig": norm(r["originalTitle"]),
                "norm_prim": norm(r["primaryTitle"]),
            }
    print(f"  {len(titulos):,} titulos cargados")

    # Cargar AKAs
    print("Cargando AKAs...")
    akas = defaultdict(list)  # tconst -> [norm_titulo, ...]
    p_akas = IMDB / "title.akas.tsv.gz"
    with gzip.open(p_akas, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["titleId"] not in titulos:
                continue
            akas[r["titleId"]].append(norm(r["title"]))
    print(f"  AKAs cargados")

    # Buscar cada pelicula
    encontradas = []
    no_encontradas = []

    for p in peliculas:
        titulo_buscar = norm(p["titulo_pelicula"])
        anio_buscar = int(p["anio"]) if p["anio"] else None
        tolerancia = 1

        candidatos = []
        for tconst, t in titulos.items():
            if anio_buscar and abs(t["anio"] - anio_buscar) > tolerancia:
                continue
            # Similitud contra titulo original, primario y AKAs
            titulos_t = [t["norm_orig"], t["norm_prim"]] + akas.get(tconst, [])
            mejor_sim = max(sim(titulo_buscar, tt) for tt in titulos_t if tt)
            if mejor_sim >= 0.85:
                candidatos.append((mejor_sim, tconst, t))

        if candidatos:
            candidatos.sort(reverse=True)
            mejor_sim, tconst, t = candidatos[0]
            encontradas.append({
                "video_id": p["video_id"],
                "titulo_video": p["titulo_video"],
                "tconst": tconst,
                "titulo_imdb": t["titulo_prim"],
                "titulo_orig": t["titulo_orig"],
                "anio_imdb": t["anio"],
                "duracion_seg": p["duracion_seg"],
                "canal": p["canal"],
                "sim": round(mejor_sim, 3),
                "confianza_ia": p.get("confianza", "alta"),
            })
            print(f"  ✓ {p['titulo_pelicula'][:40]:<40} ({p['anio']}) -> {tconst} {t['titulo_prim'][:35]} sim={mejor_sim:.2f}")
        else:
            no_encontradas.append(p)
            print(f"  ✗ {p['titulo_pelicula'][:40]:<40} ({p['anio']}) -> no encontrada")

    # Guardar
    Path("tconst_encontrados.json").write_text(
        json.dumps(encontradas, indent=2, ensure_ascii=False), encoding="utf-8")
    Path("tconst_no_encontrados.json").write_text(
        json.dumps(no_encontradas, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nEncontradas: {len(encontradas)}")
    print(f"No encontradas: {len(no_encontradas)}")
    print(f"\nRevisar tconst_encontrados.json antes de agregar.")
    print(f"Aplicar con: python3 agregar_coincidencias.py tconst_encontrados.json")


if __name__ == "__main__":
    main()
