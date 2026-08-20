#!/usr/bin/env python3
"""
generar_paginas.py
Genera páginas HTML estáticas individuales para cada película confirmada.
También genera sitemap.xml.

Output en: C:\\Users\\sebad\\Downloads\\filmoteca\\output_paginas\\
Después copiás pelicula\\ y sitemap.xml a filmoteca-web\\.

Uso:
    cd C:\\Users\\sebad\\Downloads\\filmoteca\\scripts\\
    python generar_paginas.py

Flags:
    --forzar    Regenera todas las páginas aunque ya existan
    --solo-mapa Solo regenera el sitemap.xml
"""

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path
from datetime import date

DB_PATH    = Path(__file__).resolve().parent.parent / "datos" / "filmoteca_completa.db"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output_paginas"
BASE_URL   = "https://filmotecaclasica.com"

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def slugify(texto, anio):
    """Convierte título + año a slug URL-safe."""
    s = unicodedata.normalize("NFKD", texto)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return f"{s}-{anio}"

def truncar(texto, n):
    if not texto or len(texto) <= n:
        return texto or ""
    return texto[:n].rsplit(" ", 1)[0] + "…"

def yt_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"

def yt_thumb(video_id):
    return f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

def dur_iso(seg):
    """Convierte segundos a duración ISO 8601 (PT1H30M)."""
    if not seg:
        return "PT0S"
    h = seg // 3600
    m = (seg % 3600) // 60
    s = seg % 60
    r = "PT"
    if h: r += f"{h}H"
    if m: r += f"{m}M"
    if s: r += f"{s}S"
    return r or "PT0S"

def votos_fmt(v):
    if not v:
        return ""
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.0f}K"
    return str(v)

def mes_anio(fecha_str):
    """Convierte '2021-03-15' a 'marzo 2021'."""
    if not fecha_str:
        return ""
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    try:
        partes = fecha_str[:7].split("-")
        return f"{meses[int(partes[1])-1]} {partes[0]}"
    except Exception:
        return ""

def normalizar_upload_date(fecha_str):
    """Convierte 'YYYY-MM-DD' a ISO 8601 con timezone UTC para schema VideoObject."""
    if not fecha_str:
        return None
    try:
        # Ya tiene timezone
        if "T" in fecha_str and ("+" in fecha_str or "Z" in fecha_str):
            return fecha_str
        # Solo fecha YYYY-MM-DD
        if len(fecha_str) >= 10 and fecha_str[4] == "-":
            return fecha_str[:10] + "T00:00:00+00:00"
    except Exception:
        pass
    return None

# ─── QUERY PRINCIPAL ──────────────────────────────────────────────────────────

def cargar_datos(con):
    """Carga todas las películas confirmadas con sus datos."""
    cur = con.cursor()

    # Películas confirmadas con video y datos enriquecidos
    cur.execute("""
        SELECT
            p.tconst, p.titulo_primario, p.titulo_orig, p.anio,
            p.duracion_min, p.generos, p.rating, p.votos,
            p.pais, p.poster_url, p.sinopsis, p.es_precode, p.decada,
            c.video_id, v.duracion_seg, v.publicado, v.idioma_audio,
            ca.nombre as canal
        FROM peliculas p
        JOIN coincidencias c ON c.tconst = p.tconst
        JOIN videos v ON v.video_id = c.video_id
        LEFT JOIN canales ca ON ca.channel_id = v.channel_id
        WHERE c.estado = 'confirmada'
          AND v.activo = 1
          AND (v.ve_ar = 1 OR v.ve_ar IS NULL)
        GROUP BY p.tconst
        ORDER BY p.votos DESC NULLS LAST
    """)
    cols = [d[0] for d in cur.description]
    pelis = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Personas: directores y actores por tconst
    cur.execute("""
        SELECT cr.tconst, cr.rol, pe.nombre, cr.orden
        FROM creditos cr
        JOIN personas pe ON pe.nconst = cr.nconst
        ORDER BY cr.orden
    """)
    personas = {}
    for tconst, rol, nombre, orden in cur.fetchall():
        if tconst not in personas:
            personas[tconst] = {"director": [], "actor": []}
        if rol in personas[tconst]:
            personas[tconst][rol].append(nombre)

    # Todas las versiones disponibles por tconst (para dropdown)
    cur.execute("""
        SELECT
            c.tconst, c.video_id, v.idioma_audio, ca.nombre as canal
        FROM coincidencias c
        JOIN videos v ON v.video_id = c.video_id
        LEFT JOIN canales ca ON ca.channel_id = v.channel_id
        WHERE c.estado = 'confirmada'
          AND v.activo = 1
          AND (v.ve_ar = 1 OR v.ve_ar IS NULL)
        ORDER BY c.tconst,
          CASE WHEN v.idioma_audio IN ('es', 'es-419', 'es-ES') THEN 1 ELSE 2 END,
          ca.nombre
    """)
    versiones_map = {}
    for tconst, vid, idioma, canal in cur.fetchall():
        if tconst not in versiones_map:
            versiones_map[tconst] = []
        versiones_map[tconst].append({'video_id': vid, 'idioma_audio': idioma, 'canal': canal})

    return pelis, personas, versiones_map

def precalcular_relacionadas(pelis, personas):
    """Para cada película, encuentra las 4 más relacionadas."""
    # Índices
    por_director = {}
    por_genero   = {}

    for p in pelis:
        dirs = personas.get(p["tconst"], {}).get("director", [])
        for d in dirs:
            por_director.setdefault(d, []).append(p["tconst"])

        generos = [g.strip() for g in (p["generos"] or "").split(",") if g.strip()]
        for g in generos:
            por_genero.setdefault(g, []).append(p["tconst"])

    tconst_a_peli = {p["tconst"]: p for p in pelis}
    relacionadas = {}

    for p in pelis:
        tc = p["tconst"]
        dirs = personas.get(tc, {}).get("director", [])
        generos = [g.strip() for g in (p["generos"] or "").split(",") if g.strip()]

        candidatos = {}

        # Mismo director — prioridad alta
        for d in dirs:
            for tc2 in por_director.get(d, []):
                if tc2 != tc:
                    candidatos[tc2] = candidatos.get(tc2, 0) + 2

        # Mismo género
        for g in generos:
            for tc2 in por_genero.get(g, []):
                if tc2 != tc:
                    candidatos[tc2] = candidatos.get(tc2, 0) + 1

        # Ordenar por score desc, luego por votos desc
        ordenados = sorted(
            candidatos.keys(),
            key=lambda t: (-candidatos[t], -(tconst_a_peli[t]["votos"] or 0))
        )
        relacionadas[tc] = [tconst_a_peli[t] for t in ordenados[:4] if t in tconst_a_peli]

    return relacionadas

# ─── GENERADOR HTML ───────────────────────────────────────────────────────────

CSS = """
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;1,400&family=Inter:wght@300;400;500&display=swap');
  :root{--bg:#f5f0e8;--bg2:#ede8dd;--bg3:#fff;--amber:#8b4513;--amber-dim:#c8a87a;--text:#2a1f0e;--text-dim:#6b5a40;--text-faint:#9a8a70;--border:#d4c9b0;--border2:#c4b49a;--serif:'Playfair Display',Georgia,serif;--sans:'Inter',system-ui,sans-serif;--radius:6px}
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:15px;line-height:1.6;min-height:100vh}
  a{color:inherit;text-decoration:none}
  /* NAV */
  nav{border-bottom:1px solid var(--border);padding:1rem 2rem;display:flex;align-items:baseline;justify-content:space-between;background:var(--bg);position:sticky;top:0;z-index:100}
  .logo{font-family:var(--serif);font-size:1.4rem;color:var(--text)}
  .logo em{color:var(--amber);font-style:italic}
  .nav-back{font-size:13px;color:var(--text-faint)}
  .nav-back:hover{color:var(--amber)}
  /* BREADCRUMB */
  .breadcrumb{font-size:12px;color:var(--text-faint);padding:0.6rem 2rem;border-bottom:1px solid var(--border)}
  .breadcrumb a{color:var(--text-faint)}
  .breadcrumb a:hover{color:var(--amber)}
  .breadcrumb span{margin:0 5px}
  /* LAYOUT */
  .contenedor{max-width:900px;margin:0 auto;padding:2rem}
  .layout{display:grid;grid-template-columns:220px 1fr;gap:2rem}
  @media(max-width:640px){.layout{grid-template-columns:1fr}.poster-wrap{max-width:220px;margin:0 auto}}
  /* POSTER */
  .poster-wrap img{width:100%;border-radius:var(--radius);border:1px solid var(--border);display:block}
  .poster-placeholder{width:100%;aspect-ratio:2/3;background:var(--bg2);border-radius:var(--radius);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;color:var(--text-faint);font-size:13px}
  /* INFO */
  .meta{font-size:12px;color:var(--text-faint);margin-bottom:0.4rem}
  h1{font-family:var(--serif);font-size:2rem;line-height:1.2;color:var(--text);margin-bottom:0.2rem}
  .titulo-orig{font-size:14px;color:var(--text-faint);font-style:italic;margin-bottom:1.2rem}
  /* BOTON */
  .btn-yt{display:inline-flex;align-items:center;gap:10px;background:var(--amber);color:#fff;border-radius:var(--radius);padding:12px 20px;font-size:14px;font-weight:500;margin-bottom:1.4rem;transition:background 0.15s}
  .btn-yt:hover{background:#7a3b10}
  .btn-yt-play{width:22px;height:22px;border-radius:50%;border:1.5px solid rgba(255,255,255,0.7);display:flex;align-items:center;justify-content:center;flex-shrink:0}
  .btn-yt-wrap{display:flex;flex-direction:column;gap:6px;margin-bottom:1.4rem}
  .yt-versions-dropdown{position:relative;display:inline-block}
  .yt-versions-toggle{background:none;border:1px solid var(--border);border-radius:var(--radius);padding:5px 12px;font-size:12px;color:var(--text-dim);cursor:pointer}
  .yt-versions-toggle:hover{background:var(--bg2)}
  .yt-versions-list{display:none;position:absolute;top:calc(100% + 4px);left:0;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);z-index:200;min-width:260px;box-shadow:0 4px 12px rgba(0,0,0,0.15)}
  .yt-versions-dropdown.open .yt-versions-list{display:block}
  .yt-version-item{display:block;padding:8px 14px;font-size:13px;color:var(--text);border-bottom:1px solid var(--border)}
  .yt-version-item:last-child{border-bottom:none}
  .yt-version-item:hover{background:var(--bg2)}
  /* DATOS */
  .datos-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:1.2rem}
  .dato{background:var(--bg2);border-radius:var(--radius);padding:8px 12px}
  .dato-label{font-size:10px;color:var(--text-faint);margin-bottom:2px;text-transform:uppercase;letter-spacing:0.04em}
  .dato-val{font-size:13px;color:var(--text)}
  .fila{margin-bottom:0.8rem}
  .fila-label{font-size:11px;color:var(--text-faint);margin-bottom:3px;text-transform:uppercase;letter-spacing:0.04em}
  .fila-val{font-size:14px;color:var(--text-dim)}
  .sinopsis{font-size:14px;color:var(--text-dim);line-height:1.75;margin-bottom:1.2rem}
  /* BADGES */
  .badges{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:1rem}
  .badge{font-size:11px;background:var(--bg2);border:1px solid var(--border);color:var(--text-dim);border-radius:3px;padding:2px 8px}
  .badge-special{background:rgba(139,69,19,0.08);border-color:var(--amber-dim);color:var(--amber)}
  /* CANAL Y LINKS */
  .canal-info{font-size:12px;color:var(--text-faint);padding-top:0.8rem;border-top:1px solid var(--border);margin-bottom:0.6rem}
  .links-ext{display:flex;gap:1rem}
  .link-ext{font-size:12px;color:var(--amber)}
  .link-ext:hover{text-decoration:underline}
  .report-link{color:#c0392b}
  /* RELACIONADAS */
  .relacionadas{margin-top:2.5rem;border-top:1px solid var(--border);padding-top:1.5rem}
  .rel-titulo{font-size:11px;color:var(--text-faint);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:1rem}
  .rel-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
  @media(max-width:640px){.rel-grid{grid-template-columns:repeat(2,1fr)}}
  .rel-card{display:block;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;transition:border-color 0.15s}
  .rel-card:hover{border-color:var(--amber-dim)}
  .rel-poster img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block}
  .rel-placeholder{width:100%;aspect-ratio:2/3;background:var(--bg2);display:flex;align-items:center;justify-content:center;color:var(--text-faint);font-size:11px}
  .rel-info{padding:6px 8px}
  .rel-titulo-peli{font-size:11px;color:var(--text);line-height:1.3;margin-bottom:2px}
  .rel-anio{font-size:10px;color:var(--text-faint)}
  /* FOOTER */
  footer{border-top:1px solid var(--border);padding:1.2rem 2rem;text-align:center;font-size:12px;color:var(--text-faint);margin-top:3rem}
  /* BOTONES USUARIO */
  .user-actions{display:flex;gap:8px;margin-bottom:1.2rem}
  .btn-usuario{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:var(--radius);border:1px solid var(--border);background:var(--bg3);color:var(--text-dim);font-size:13px;font-family:var(--sans);cursor:pointer;transition:all 0.15s}
  .btn-usuario:hover{border-color:var(--amber-dim);color:var(--text)}
  .btn-usuario.activo{background:rgba(139,69,19,0.08);border-color:var(--amber-dim);color:var(--amber)}
  .btn-usuario.oculto{display:none}
"""

def generar_html(p, dirs, actores, rel, slug, versiones=None):
    titulo    = p["titulo_primario"] or ""
    orig      = p["titulo_orig"] or ""
    anio      = p["anio"] or ""
    dur       = p["duracion_min"]
    generos   = p["generos"] or ""
    rating    = p["rating"]
    votos     = p["votos"]
    pais      = p["pais"] or ""
    poster    = p["poster_url"] or ""
    sinopsis  = p["sinopsis"] or ""
    precode   = p["es_precode"]
    video_id  = p["video_id"]
    dur_seg   = p["duracion_seg"]
    publicado = p["publicado"] or ""
    idioma    = p["idioma_audio"] or ""
    canal     = p["canal"] or ""
    tconst    = p["tconst"]
    decada    = p["decada"]

    # Botón de YouTube — simple o dropdown según versiones disponibles
    IDIOMA_MAP_BTN = {
        'es': 'Español', 'es-419': 'Español', 'es-ES': 'Español',
        'en': 'Inglés', 'en-US': 'Inglés', 'en-GB': 'Inglés', 'en-IN': 'Inglés',
        'fr': 'Francés', 'it': 'Italiano', 'ru': 'Ruso',
        'de': 'Alemán', 'ja': 'Japonés', 'pt': 'Portugués',
    }
    play_icon = '<div class="btn-yt-play"><svg width="8" height="9" viewBox="0 0 8 9" fill="white"><polygon points="2,1 7,4.5 2,8"/></svg></div>'
    if not versiones or len(versiones) <= 1:
        btn_yt_html = f'<a class="btn-yt" href="{yt_url(video_id)}" target="_blank" rel="noopener">{play_icon}Ver en YouTube · gratis y completa</a>'
    else:
        items = []
        for v in versiones:
            idioma_label = IDIOMA_MAP_BTN.get(v['idioma_audio'] or '', v['idioma_audio'] or 'Idioma desconocido')
            canal_label = v['canal'] or 'Canal desconocido'
            items.append(f'<a class="yt-version-item" href="{yt_url(v["video_id"])}" target="_blank" rel="noopener">{canal_label} · {idioma_label}</a>')
        items_html = '\n'.join(items)
        btn_yt_html = f'''<div class="btn-yt-wrap">
  <a class="btn-yt" href="{yt_url(versiones[0]["video_id"])}" target="_blank" rel="noopener">{play_icon}Ver en YouTube · gratis y completa</a>
  <div class="yt-versions-dropdown">
    <button class="yt-versions-toggle" onclick="this.parentElement.classList.toggle(\'open\')">▾ {len(versiones)} versiones</button>
    <div class="yt-versions-list">{items_html}</div>
  </div>
</div>'''

    meta_title = f"Ver {titulo} ({anio}) completa gratis en YouTube | Filmoteca Clásica"
    meta_desc  = truncar(sinopsis, 155) if sinopsis else f"{titulo} ({anio}) — disponible gratis y completa en YouTube. Verificada desde Argentina."
    url_peli   = f"{BASE_URL}/pelicula/{slug}/"
    url_decada = f"{BASE_URL}/#decada={decada}"
    url_imdb   = f"https://www.imdb.com/title/{tconst}/"
    report_url = f"https://docs.google.com/forms/d/e/1FAIpQLScAs0NejYOuO4ewlUIzs6e86fRGLAM3yjhgChSxIUfuEPuFmg/viewform?entry.1007045909={titulo}&entry.717085040={video_id}"

    # Schema.org JSON-LD
    director_schema = [{"@type": "Person", "name": d} for d in dirs[:2]]
    actores_schema  = [{"@type": "Person", "name": a} for a in actores[:5]]
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Movie",
                "name": titulo,
                "alternateName": orig if orig != titulo else None,
                "dateCreated": str(anio),
                "duration": dur_iso(dur_seg),
                "director": director_schema or None,
                "actor": actores_schema or None,
                "countryOfOrigin": pais.split(",")[0].strip() if pais else None,
                "genre": [g.strip() for g in generos.split(",") if g.strip()],
                "description": sinopsis or None,
                "image": poster or None,
                "url": url_peli,
                "sameAs": url_imdb,
            },
            {
                "@type": "VideoObject",
                "name": f"{titulo} ({anio}) — completa en YouTube",
                "description": sinopsis or f"{titulo} ({anio}). Película clásica disponible completa y gratuita en YouTube. Verificada desde Argentina.",
                "thumbnailUrl": yt_thumb(video_id),
                "contentUrl": yt_url(video_id),
                "uploadDate": normalizar_upload_date(publicado),
                "duration": dur_iso(dur_seg),
                "url": yt_url(video_id),
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Filmoteca Clásica", "item": BASE_URL},
                    {"@type": "ListItem", "position": 2, "name": f"{decada}s", "item": url_decada},
                    {"@type": "ListItem", "position": 3, "name": titulo, "item": url_peli},
                ]
            }
        ]
    }
    # Limpiar nulos del schema
    import json
    def limpiar(obj):
        if isinstance(obj, dict):
            return {k: limpiar(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, list):
            return [limpiar(i) for i in obj]
        return obj
    schema_str = json.dumps(limpiar(schema), ensure_ascii=False, indent=2)

    # Poster
    if poster:
        poster_html = f'<img src="{poster}" alt="Póster de {titulo}" loading="lazy">'
    else:
        poster_html = f'<div class="poster-placeholder">{titulo[:20]}</div>'

    # Géneros como badges
    gen_list = [g.strip() for g in generos.split(",") if g.strip()]
    badges = "".join(f'<span class="badge">{g}</span>' for g in gen_list)
    if precode == 1:
        badges += '<span class="badge badge-special">Pre-Code</span>'
    elif precode == 2:
        badges += '<span class="badge badge-special">Pre-Code (1934)</span>'

    # Idioma
    IDIOMA_MAP = {
        'es': 'Español', 'es-419': 'Español', 'es-ES': 'Español',
        'en': 'Inglés', 'en-US': 'Inglés', 'en-GB': 'Inglés', 'en-IN': 'Inglés',
        'fr': 'Francés', 'it': 'Italiano', 'ru': 'Ruso',
        'de': 'Alemán', 'ja': 'Japonés', 'pt': 'Portugués',
    }
    idioma_txt = IDIOMA_MAP.get(idioma, idioma or "")

    # Datos grid
    datos = []
    if pais:
        datos.append(("País", pais))
    if rating:
        votos_txt = f" · {votos_fmt(votos)} votos" if votos else ""
        datos.append(("Rating IMDb", f"★ {rating:.1f}{votos_txt}"))
    if idioma_txt:
        datos.append(("Idioma", idioma_txt))
    if publicado:
        datos.append(("En YouTube desde", mes_anio(publicado)))

    datos_html = ""
    for label, val in datos:
        datos_html += f'<div class="dato"><div class="dato-label">{label}</div><div class="dato-val">{val}</div></div>'

    # Relacionadas
    rel_html = ""
    for r in rel:
        r_slug = slugify(r["titulo_primario"] or "", r["anio"])
        r_poster = f'<img src="{r["poster_url"]}" alt="{r["titulo_primario"]}" loading="lazy">' if r["poster_url"] else f'<div class="rel-placeholder">{(r["titulo_primario"] or "")[:15]}</div>'
        rel_html += f'''
        <a class="rel-card" href="{BASE_URL}/pelicula/{r_slug}/">
          <div class="rel-poster">{r_poster}</div>
          <div class="rel-info">
            <div class="rel-titulo-peli">{r["titulo_primario"]}</div>
            <div class="rel-anio">{r["anio"]}</div>
          </div>
        </a>'''

    # Título original solo si es distinto
    orig_html = f'<div class="titulo-orig">{orig}</div>' if orig and orig != titulo else ""

    # Director y reparto
    dir_html = ""
    if dirs:
        dir_html = f'<div class="fila"><div class="fila-label">Director</div><div class="fila-val">{", ".join(dirs[:2])}</div></div>'
    act_html = ""
    if actores:
        act_html = f'<div class="fila"><div class="fila-label">Reparto</div><div class="fila-val">{", ".join(actores[:6])}</div></div>'

    meta_str = " · ".join(filter(None, [str(anio), f"{dur} min" if dur else None, gen_list[0] if gen_list else None]))

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{meta_title}</title>
<meta name="description" content="{meta_desc}">
<meta property="og:title" content="{meta_title}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{poster or yt_thumb(video_id)}">
<meta property="og:url" content="{url_peli}">
<meta property="og:type" content="video.movie">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{url_peli}">
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-FNBHN0F639"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-FNBHN0F639');
</script>
<script type="application/ld+json">
{schema_str}
</script>
<style>{CSS}</style>
</head>
<body>

<nav>
  <a class="logo" href="{BASE_URL}">Filmoteca <em>Clásica</em></a>
  <a class="nav-back" href="{BASE_URL}">← Volver al catálogo</a>
</nav>

<div class="breadcrumb">
  <a href="{BASE_URL}">Filmoteca Clásica</a>
  <span>›</span>
  <a href="{url_decada}">{decada}s</a>
  <span>›</span>
  {titulo}
</div>

<div class="contenedor">
  <div class="layout">

    <div class="poster-wrap">
      {poster_html}
    </div>

    <div>
      <div class="meta">{meta_str}</div>
      <h1>{titulo}</h1>
      {orig_html}

      {btn_yt_html}

      <div class="user-actions" id="user-actions" style="display:none">
        <button class="btn-usuario" id="btn-fav" onclick="toggleFav()">🤍 Favorita</button>
        <button class="btn-usuario" id="btn-vista" onclick="toggleVista()">⬜ Marcar como vista</button>
      </div>

      {dir_html}
      {act_html}

      <div class="datos-grid">
        {datos_html}
      </div>

      {f'<div class="sinopsis">{sinopsis}</div>' if sinopsis else ""}

      <div class="badges">{badges}</div>

      <div class="canal-info">
        {'Disponible en ' + str(len(versiones)) + ' versiones · verificada desde Argentina' if versiones and len(versiones) > 1 else f'Disponible en <strong>{canal}</strong> · verificada desde Argentina'}
      </div>

      <div class="links-ext">
        <a class="link-ext" href="{url_imdb}" target="_blank" rel="noopener">Ver ficha en IMDb ↗</a>
        <a class="link-ext" href="{url_decada}">Ver década de {decada} →</a>
        <a class="link-ext report-link" href="{report_url}" target="_blank" rel="noopener">⚑ Reportar problema</a>
      </div>


    </div>
  </div>

  {f'''
  <div class="relacionadas">
    <div class="rel-titulo">Películas relacionadas</div>
    <div class="rel-grid">
      {rel_html}
    </div>
  </div>''' if rel_html else ""}

</div>

<footer>
  Filmoteca Clásica · catálogo de cine clásico gratis en YouTube · sin publicidad · <a href="https://github.com/sebadetoma-stack/filmoteca" style="color:var(--text-faint)">código abierto</a>
</footer>

<script type="module">
import {{ initializeApp }} from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js';
import {{ getAuth, onAuthStateChanged }} from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js';
import {{ getFirestore, doc, getDoc, setDoc, deleteDoc, serverTimestamp }} from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-firestore.js';

const firebaseConfig = {{
  apiKey: "AIzaSyBh2sTmHwED1VtlvIqMOy1wFcW8CO_NZNg",
  authDomain: "filmoteca-clasica.firebaseapp.com",
  projectId: "filmoteca-clasica",
  storageBucket: "filmoteca-clasica.firebasestorage.app",
  messagingSenderId: "347321323128",
  appId: "1:347321323128:web:0dc5899523d9a8cffb678d"
}};

const TCONST = "{tconst}";
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

let uid = null;
let esFav = false;
let esVista = false;

onAuthStateChanged(auth, async (user) => {{
  if (!user) return;
  uid = user.uid;
  document.getElementById('user-actions').style.display = 'flex';

  // Cargar estado
  const [favDoc, vistaDoc] = await Promise.all([
    getDoc(doc(db, 'usuarios', uid, 'favoritos', TCONST)),
    getDoc(doc(db, 'usuarios', uid, 'vistos', TCONST))
  ]);
  esFav = favDoc.exists();
  esVista = vistaDoc.exists();
  actualizarBotones();
}});

function actualizarBotones() {{
  const btnFav = document.getElementById('btn-fav');
  const btnVista = document.getElementById('btn-vista');
  btnFav.textContent = esFav ? '❤️ En favoritos' : '🤍 Favorita';
  btnFav.classList.toggle('activo', esFav);
  btnVista.textContent = esVista ? '✅ Vista' : '⬜ Marcar como vista';
  btnVista.classList.toggle('activo', esVista);
}}

window.toggleFav = async function() {{
  if (!uid) return;
  const ref = doc(db, 'usuarios', uid, 'favoritos', TCONST);
  if (esFav) {{ await deleteDoc(ref); esFav = false; }}
  else {{ await setDoc(ref, {{ tconst: TCONST, fecha: serverTimestamp() }}); esFav = true; }}
  actualizarBotones();
}};

window.toggleVista = async function() {{
  if (!uid) return;
  const ref = doc(db, 'usuarios', uid, 'vistos', TCONST);
  if (esVista) {{ await deleteDoc(ref); esVista = false; }}
  else {{ await setDoc(ref, {{ tconst: TCONST, fecha: serverTimestamp() }}); esVista = true; }}
  actualizarBotones();
}};
</script>

</body>
</html>"""

# ─── SITEMAP ──────────────────────────────────────────────────────────────────

def generar_sitemap(slugs_urls):
    hoy = date.today().isoformat()
    items = "\n".join(
        f"  <url><loc>{url}</loc><lastmod>{hoy}</lastmod><changefreq>monthly</changefreq><priority>0.8</priority></url>"
        for url in slugs_urls
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE_URL}/</loc><lastmod>{hoy}</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>
{items}
</urlset>"""

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forzar", action="store_true", help="Regenera todas las páginas")
    ap.add_argument("--solo-mapa", action="store_true", help="Solo regenera sitemap.xml")
    args = ap.parse_args()

    print(f"\n{'='*55}")
    print(f"  Generador de páginas estáticas — Filmoteca Clásica")
    print(f"{'='*55}\n")

    con = sqlite3.connect(DB_PATH)
    print("Cargando datos...")
    pelis, personas, versiones_map = cargar_datos(con)
    con.close()
    print(f"  → {len(pelis):,} películas confirmadas\n")

    print("Calculando relacionadas...")
    relacionadas = precalcular_relacionadas(pelis, personas)
    print(f"  → listo\n")

    # Crear directorios
    dir_pelis = OUTPUT_DIR / "pelicula"
    dir_pelis.mkdir(parents=True, exist_ok=True)

    urls = []
    generadas = 0
    saltadas  = 0

    if not args.solo_mapa:
        print("Generando páginas...")
        for i, p in enumerate(pelis):
            slug = slugify(p["titulo_primario"] or p["titulo_orig"] or f"pelicula-{p['tconst']}", p["anio"])
            url  = f"{BASE_URL}/pelicula/{slug}/"
            urls.append(url)

            destino = dir_pelis / slug / "index.html"

            if not args.forzar and destino.exists():
                saltadas += 1
                continue

            dirs    = personas.get(p["tconst"], {}).get("director", [])
            actores = personas.get(p["tconst"], {}).get("actor", [])
            rel     = relacionadas.get(p["tconst"], [])
            versiones = versiones_map.get(p["tconst"], [])

            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(generar_html(p, dirs, actores, rel, slug, versiones), encoding="utf-8")
            generadas += 1

            if (i + 1) % 200 == 0:
                print(f"  {i+1:>5}/{len(pelis)} — {generadas} generadas, {saltadas} saltadas")

        print(f"\n  Total: {generadas} generadas, {saltadas} ya existían\n")
    else:
        # Solo para sitemap necesitamos los slugs
        for p in pelis:
            slug = slugify(p["titulo_primario"] or p["titulo_orig"] or f"pelicula-{p['tconst']}", p["anio"])
            urls.append(f"{BASE_URL}/pelicula/{slug}/")

    # Sitemap
    print("Generando sitemap.xml...")
    sitemap_path = OUTPUT_DIR / "sitemap.xml"
    sitemap_path.write_text(generar_sitemap(urls), encoding="utf-8")
    print(f"  → {sitemap_path}")
    print(f"  → {len(urls):,} URLs incluidas\n")

    print(f"{'='*55}")
    print(f"  Output en: {OUTPUT_DIR}")
    print(f"  Copiá 'pelicula\\' y 'sitemap.xml' a filmoteca-web\\")
    print(f"{'='*55}\n")

if __name__ == "__main__":
    main()
