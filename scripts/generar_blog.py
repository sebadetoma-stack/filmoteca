#!/usr/bin/env python3
"""
Generador del blog de Filmoteca Clásica.
Convierte archivos .md en posts/  a HTML en filmoteca-web/blog/

Estructura de un post .md:
---
titulo: Casablanca: por qué sigue siendo perfecta
categoria: Reseñas
fecha: 2026-08-12
imagen: casablanca-hero.jpg
slug: casablanca-por-que-sigue-siendo-perfecta
---
Contenido del artículo en Markdown...

Uso: python scripts\generar_blog.py
"""
import re
import os
import shutil
import json
import sqlite3
import urllib.request
import urllib.parse
import urllib.error
import time
import base64
from pathlib import Path
from datetime import datetime

BASE      = Path(__file__).resolve().parent.parent
POSTS_DIR = BASE / "blog" / "posts"
WEB_DIR   = Path(r"C:\Users\sebad\Downloads\filmoteca-web") / "blog"
IMG_DIR   = BASE / "blog" / "imagenes"
DB_PATH   = BASE / "datos" / "filmoteca_completa.db"
GA4_CREDENTIALS = BASE / "datos" / "google_analytics_credentials.json"
GA4_PROPERTY_ID = "550089683"

CATEGORIAS = [
    "Reseñas",
    "Directores",
    "Géneros",
    "Historia del cine",
    "Recomendaciones",
    "Cómo lo hacemos",
]

CSS = """
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;1,400&family=Inter:wght@300;400;500&display=swap');
  :root{--bg:#f5f0e8;--bg2:#ede8dd;--bg3:#fff;--amber:#8b4513;--amber-dim:#c8a87a;--text:#2a1f0e;--text-dim:#6b5a40;--text-faint:#9a8a70;--border:#d4c9b0;--serif:'Playfair Display',Georgia,serif;--sans:'Inter',system-ui,sans-serif;--radius:6px}
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:15px;line-height:1.6;min-height:100vh}
  a{color:inherit;text-decoration:none}
  nav{border-bottom:1px solid var(--border);padding:1rem 2rem;display:flex;align-items:center;gap:1rem;background:var(--bg);position:sticky;top:0;z-index:100}
  .logo{font-family:var(--serif);font-size:1.25rem;color:var(--text)}
  .logo em{color:var(--amber);font-style:italic}
  .logo-sub{font-size:11px;color:var(--text-faint);letter-spacing:0.12em;text-transform:uppercase}
  .nav-links{display:flex;gap:0.5rem;align-items:center;margin-left:auto}
  .nav-link{font-size:12px;color:var(--text-faint);padding:4px 8px;transition:color 0.15s}
  .nav-link:hover{color:var(--amber)}
  .nav-blog{background:var(--amber);color:#fff;border-radius:4px;padding:4px 10px;font-size:12px;font-family:var(--sans)}
  .nav-blog:hover{opacity:0.85;color:#fff}
  .nav-back{font-size:12px;color:var(--text-faint)}
  .nav-back:hover{color:var(--amber)}

  /* ÍNDICE */
  .blog-header{max-width:700px;margin:2rem auto 1.5rem;padding:0 1.5rem}
  .blog-title{font-family:var(--serif);font-size:2rem;color:var(--text);margin-bottom:4px}
  .blog-sub{font-size:13px;color:var(--text-faint)}
  .cat-filter{max-width:700px;margin:0 auto 1.5rem;padding:0 1.5rem;display:flex;gap:8px;flex-wrap:wrap}
  .cat-btn{font-size:11px;padding:4px 12px;border-radius:20px;border:1px solid var(--border);color:var(--text-faint);background:transparent;cursor:pointer;font-family:var(--sans);transition:all 0.15s}
  .cat-btn:hover,.cat-btn.active{background:var(--amber);border-color:var(--amber);color:#fff}
  .posts-list{max-width:700px;margin:0 auto;padding:0 1.5rem 4rem;display:flex;flex-direction:column;gap:12px}
  .post-card{background:var(--bg3);border:1px solid var(--border);border-radius:8px;overflow:hidden;display:flex;transition:border-color 0.15s}
  .post-card:hover{border-color:var(--amber-dim)}
  .post-img{width:120px;flex-shrink:0;background:var(--bg2);overflow:hidden}
  .post-img img{width:100%;height:100%;object-fit:cover;display:block}
  .post-img-placeholder{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:2rem}
  .post-body{flex:1;padding:14px 16px;display:flex;flex-direction:column;gap:4px}
  .post-cat{font-size:10px;color:var(--amber);text-transform:uppercase;letter-spacing:0.08em;font-family:var(--sans)}
  .post-title{font-family:var(--serif);font-size:15px;color:var(--text);line-height:1.3}
  .post-excerpt{font-size:12px;color:var(--text-dim);line-height:1.5;flex:1}
  .post-footer{display:flex;justify-content:space-between;align-items:center;margin-top:4px}
  .post-meta{font-size:10px;color:var(--text-faint);font-family:var(--sans)}
  .leer-mas{font-size:11px;color:var(--amber);font-family:var(--sans)}

  /* ARTÍCULO */
  .article-hero{width:100%;display:flex;flex-direction:column;align-items:center;padding:1.5rem 0 0}
  .article-hero img{max-width:800px;width:100%;height:auto;display:block}
  .article-hero-credito{font-size:10px;color:var(--text-faint);text-align:center;padding:4px 0 0;font-family:var(--sans);max-width:800px;width:100%}
  .article-hero-credito a{color:var(--text-faint)}
  .article-wrap{max-width:680px;margin:0 auto;padding:2rem 1.5rem 4rem}
  .article-cat{font-size:11px;color:var(--amber);text-transform:uppercase;letter-spacing:0.1em;font-family:var(--sans);margin-bottom:8px}
  .article-title{font-family:var(--serif);font-size:2rem;line-height:1.2;color:var(--text);margin-bottom:10px}
  .article-meta{font-size:12px;color:var(--text-faint);font-family:var(--sans);margin-bottom:1.5rem;padding-bottom:1.5rem;border-bottom:1px solid var(--border)}
  .article-body{font-family:var(--serif);font-size:16px;line-height:1.8;color:var(--text-dim)}
  .article-body p{margin-bottom:1.2rem}
  .article-body h2{font-family:var(--serif);font-size:1.4rem;color:var(--text);margin:2rem 0 0.75rem}
  .article-body h3{font-family:var(--serif);font-size:1.1rem;color:var(--text);margin:1.5rem 0 0.5rem}
  .article-body blockquote{border-left:3px solid var(--amber-dim);padding-left:1rem;margin:1.5rem 0;font-style:italic;color:var(--text-faint)}
  .article-body a{color:var(--amber);text-decoration:underline}
  .article-body strong{color:var(--text);font-weight:600}
  .article-figure{margin:1.5rem 0;text-align:center}
  .article-figure img{max-width:100%;height:auto;border-radius:4px}
  .article-figure figcaption{font-size:12px;color:var(--text-faint);font-family:var(--sans);margin-top:6px;font-style:italic}
  .article-divider{height:1px;background:var(--border);margin:2rem 0}
  .rel-titulo{font-size:11px;color:var(--text-faint);text-transform:uppercase;letter-spacing:0.08em;font-family:var(--sans);margin-bottom:1rem}
  .rel-list{display:flex;flex-direction:column;gap:10px}
  .rel-item{display:flex;gap:10px;align-items:center;padding:8px;border-radius:6px;transition:background 0.15s}
  .rel-item:hover{background:var(--bg2)}
  .rel-img{width:54px;height:54px;background:var(--bg2);border-radius:4px;overflow:hidden;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:1.5rem}
  .rel-img img{width:100%;height:100%;object-fit:cover}
  .rel-cat{font-size:9px;color:var(--amber);text-transform:uppercase;letter-spacing:0.06em;font-family:var(--sans)}
  .rel-name{font-size:12px;color:var(--text);font-family:var(--serif);line-height:1.3}

  footer{border-top:1px solid var(--border);padding:1.2rem 2rem;text-align:center;font-size:12px;color:var(--text-faint);margin-top:3rem}

  /* SIDEBAR */
  .article-layout{max-width:960px;margin:0 auto;padding:2rem 1.5rem 4rem;display:grid;grid-template-columns:1fr 200px;gap:2.5rem;align-items:start}
  .article-main{min-width:0}
  .sidebar{position:sticky;top:80px}
  .sidebar-titulo{font-size:10px;color:var(--amber);text-transform:uppercase;letter-spacing:0.1em;font-family:var(--sans);margin-bottom:0.75rem}
  .sidebar-item{display:flex;gap:8px;margin-bottom:0.75rem;align-items:flex-start;text-decoration:none}
  .sidebar-item:hover .sidebar-nombre{color:var(--amber)}
  .sidebar-poster{width:36px;height:52px;object-fit:cover;border-radius:3px;flex-shrink:0;background:var(--bg2)}
  .sidebar-poster-placeholder{width:36px;height:52px;border-radius:3px;flex-shrink:0;background:var(--bg2);display:flex;align-items:center;justify-content:center;font-size:1.2rem}
  .sidebar-info{flex:1;min-width:0}
  .sidebar-nombre{font-size:12px;line-height:1.3;color:var(--text);font-family:var(--serif);transition:color 0.15s}
  .sidebar-anio{font-size:11px;color:var(--text-faint);font-family:var(--sans)}

  @media(max-width:700px){
    .article-layout{grid-template-columns:1fr;padding:1.5rem 1rem 3rem}
    .sidebar{position:static;border-top:1px solid var(--border);padding-top:1.5rem;margin-top:1rem}
  }
  @media(max-width:600px){
    nav{padding:0.75rem 1rem}
    .article-wrap,.blog-header,.cat-filter,.posts-list{padding-left:1rem;padding-right:1rem}
    .article-title{font-size:1.5rem}
    .post-img{width:90px}
  }
"""

GA4 = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-FNBHN0F639"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-FNBHN0F639');
</script>"""

FIREBASE_SCRIPT = """<script type="module">
import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js';
import { getAuth, onAuthStateChanged, GoogleAuthProvider, signInWithPopup, signOut } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js';
import { getFirestore, doc, getDoc, setDoc, serverTimestamp } from 'https://www.gstatic.com/firebasejs/10.7.1/firebase-firestore.js';
const firebaseConfig = {
  apiKey: "AIzaSyBh2sTmHwED1VtlvIqMOy1wFcW8CO_NZNg",
  authDomain: "filmoteca-clasica.firebaseapp.com",
  projectId: "filmoteca-clasica",
  storageBucket: "filmoteca-clasica.firebasestorage.app",
  messagingSenderId: "347321323128",
  appId: "1:347321323128:web:0dc5899523d9a8cffb678d"
};
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const provider = new GoogleAuthProvider();
const db = getFirestore(app);
onAuthStateChanged(auth, async (user) => {
  if (user) {
    document.getElementById('btn-login-nav')?.style && (document.getElementById('btn-login-nav').style.display = 'none');
    const av = document.getElementById('user-avatar-nav');
    if (av) {
      av.style.display = 'flex';
      const perfilDoc = await getDoc(doc(db, 'perfiles', user.uid));
      const perfil = perfilDoc.exists() ? perfilDoc.data() : {};
      const AVATARES = ['🎬','🎥','🎞️','📽️','🎟️','🍿','🎦','🎙️','🕵️','🎭'];
      const el = av.querySelector('.av-iniciales');
      if (perfil.avatar && AVATARES.includes(perfil.avatar)) {
        el.textContent = perfil.avatar; el.style.fontSize = '14px';
      } else {
        const nombre = perfil.nombre || user.displayName || '';
        el.textContent = nombre.split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase() || '?';
      }
    }
  } else {
    document.getElementById('btn-login-nav')?.style && (document.getElementById('btn-login-nav').style.display = 'block');
    document.getElementById('user-avatar-nav')?.style && (document.getElementById('user-avatar-nav').style.display = 'none');
  }
});
window.loginConGoogle = async () => { try { await signInWithPopup(auth, provider); } catch(e){} };
window.cerrarSesion = async () => { await signOut(auth); };
window.toggleDropdownNav = (e) => { e.stopPropagation(); document.getElementById('user-avatar-nav')?.classList.toggle('open'); };
document.addEventListener('click', () => document.getElementById('user-avatar-nav')?.classList.remove('open'));
</script>"""

NAV_CSS = """
  .user-avatar-nav {
    width: 28px; height: 28px; border-radius: 50%;
    background: var(--amber); color: #fff;
    display: none; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 600; cursor: pointer; flex-shrink: 0;
    position: relative;
  }
  .user-avatar-nav.open .user-dropdown-nav { display: block; }
  .user-dropdown-nav {
    display: none; position: absolute; top: calc(100% + 8px); right: 0;
    background: var(--bg3); border: 1px solid var(--border);
    border-radius: 8px; padding: 4px 0; min-width: 160px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.12); z-index: 200; font-family: var(--sans);
  }
  .dd-item-nav { padding: 6px 14px; font-size: 12px; color: var(--text-dim); cursor: pointer; }
  .dd-item-nav:hover { background: var(--bg2); }
  .dd-divider-nav { height: 1px; background: var(--border); margin: 4px 0; }
"""


def get_access_token():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        print("  ✗ Falta cryptography: pip install cryptography --break-system-packages")
        return None
    with open(GA4_CREDENTIALS, encoding="utf-8") as f:
        creds = json.load(f)
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iss": creds["client_email"], "scope": "https://www.googleapis.com/auth/analytics.readonly", "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}
    def b64url(data):
        if isinstance(data, dict): data = json.dumps(data, separators=(',', ':')).encode()
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    header_b64 = b64url(header); payload_b64 = b64url(payload)
    signing_input = f"{header_b64}.{payload_b64}".encode()
    private_key = serialization.load_pem_private_key(creds["private_key"].encode(), password=None, backend=default_backend())
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{header_b64}.{payload_b64}.{b64url(signature)}"
    data = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read()).get("access_token")


def obtener_mas_vistas():
    if not GA4_CREDENTIALS.exists():
        print("  ✗ No se encontró google_analytics_credentials.json")
        return []
    try:
        token = get_access_token()
        if not token: return []
        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY_ID}:runReport"
        body = {"dateRanges": [{"startDate": "30daysAgo", "endDate": "today"}], "dimensions": [{"name": "pagePath"}], "metrics": [{"name": "screenPageViews"}], "dimensionFilter": {"filter": {"fieldName": "pagePath", "stringFilter": {"matchType": "BEGINS_WITH", "value": "/pelicula/"}}}, "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}], "limit": 20}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            rows = json.loads(resp.read()).get("rows", [])
        slugs = []
        for row in rows:
            path = row["dimensionValues"][0]["value"]
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2: slugs.append(parts[1])
        return slugs
    except Exception as e:
        print(f"  ✗ Error consultando GA4: {e}")
        return []


def slug_desde_titulo(titulo, anio):
    import unicodedata as _ud
    s = _ud.normalize("NFKD", titulo)
    s = "".join(c for c in s if not _ud.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return f"{s}-{anio}"


def obtener_datos_peliculas(slugs):
    if not slugs or not DB_PATH.exists(): return []
    resultados = []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT p.tconst, p.titulo_primario, p.titulo_orig, p.titulo_es, p.anio, p.poster_url
            FROM peliculas p
            JOIN coincidencias c ON p.tconst = c.tconst
            JOIN videos v ON v.video_id = c.video_id
            WHERE c.estado = 'confirmada' AND v.activo = 1
        """)
        rows = cur.fetchall()
        conn.close()
        indice = {}
        for row in rows:
            texto = row["titulo_primario"] or row["titulo_orig"] or f"pelicula-{row['tconst']}"
            s = slug_desde_titulo(texto, row["anio"])
            indice[s] = {"slug": s, "titulo": row["titulo_es"] or row["titulo_primario"] or row["titulo_orig"], "anio": row["anio"], "poster": row["poster_url"] or ""}
        for slug in slugs:
            if slug in indice: resultados.append(indice[slug])
            if len(resultados) >= 10: break
    except Exception as e:
        print(f"  ✗ Error consultando DB para sidebar: {e}")
    return resultados


def generar_sidebar_html(peliculas):
    if not peliculas: return ""
    items = []
    for p in peliculas:
        url = f"https://filmotecaclasica.com/pelicula/{p['slug']}/"
        if p["poster"]:
            img_html = f'<img class="sidebar-poster" src="{p["poster"]}" alt="{p["titulo"]}" loading="lazy">'
        else:
            img_html = '<div class="sidebar-poster-placeholder">🎬</div>'
        items.append(f'<a class="sidebar-item" href="{url}">{img_html}<div class="sidebar-info"><div class="sidebar-nombre">{p["titulo"]}</div><div class="sidebar-anio">{p["anio"]}</div></div></a>')
    return f'<aside class="sidebar"><div class="sidebar-titulo">Las 10 más vistas de los últimos días</div>{"".join(items)}</aside>'


def parsear_md(path):
    """Lee un archivo .md y devuelve (meta, contenido_html)"""
    text = path.read_text(encoding='utf-8')
    # Extraer frontmatter
    m = re.match(r'^---\n(.*?)\n---\n(.*)', text, re.DOTALL)
    if not m:
        raise ValueError(f"Falta frontmatter en {path}")
    meta_raw, contenido = m.group(1), m.group(2)
    meta = {}
    for line in meta_raw.strip().split('\n'):
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip()
    # Convertir Markdown básico a HTML
    html = md_a_html(contenido.strip())
    return meta, html


def md_a_html(texto):
    """Conversión Markdown básica a HTML"""
    lineas = texto.split('\n')
    html = []
    en_parrafo = False

    for linea in lineas:
        linea_strip = linea.strip()

        if linea_strip.startswith('## '):
            if en_parrafo: html.append('</p>'); en_parrafo = False
            html.append(f'<h2>{linea_strip[3:]}</h2>')
        elif linea_strip.startswith('### '):
            if en_parrafo: html.append('</p>'); en_parrafo = False
            html.append(f'<h3>{linea_strip[4:]}</h3>')
        elif linea_strip.startswith('> '):
            if en_parrafo: html.append('</p>'); en_parrafo = False
            html.append(f'<blockquote>{linea_strip[2:]}</blockquote>')
        elif linea_strip == '':
            if en_parrafo: html.append('</p>'); en_parrafo = False
        elif re.match(r'!\[(.+?)\]\((.+?)\)', linea_strip):
            # Imagen con epígrafe: ![epígrafe](nombre.jpg)
            if en_parrafo: html.append('</p>'); en_parrafo = False
            m = re.match(r'!\[(.+?)\]\((.+?)\)', linea_strip)
            epigrafe = m.group(1)
            src = m.group(2)
            if not src.startswith('http'):
                src = f'/blog/imagenes/{src}'
            html.append(f'<figure class="article-figure"><img src="{src}" alt="{epigrafe}"><figcaption>{epigrafe}</figcaption></figure>')
        else:
            # Inline: bold, italic, links
            linea_strip = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', linea_strip)
            linea_strip = re.sub(r'\*(.+?)\*', r'<em>\1</em>', linea_strip)
            linea_strip = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', linea_strip)
            if not en_parrafo:
                html.append('<p>'); en_parrafo = True
            else:
                html.append(' ')
            html.append(linea_strip)

    if en_parrafo: html.append('</p>')
    return '\n'.join(html)


def formatear_fecha(fecha_str):
    """'2026-08-12' → '12 de agosto de 2026'"""
    meses = ['enero','febrero','marzo','abril','mayo','junio',
             'julio','agosto','septiembre','octubre','noviembre','diciembre']
    try:
        d = datetime.strptime(fecha_str, '%Y-%m-%d')
        return f'{d.day} de {meses[d.month-1]} de {d.year}'
    except Exception:
        return fecha_str


def nav_html(activo='blog'):
    return f"""<nav>
  <a href="https://filmotecaclasica.com" style="text-decoration:none">
    <div class="logo">Filmoteca <em>Clásica</em></div>
    <div class="logo-sub">1920 – 1979</div>
  </a>
  <div class="nav-links">
    <a href="https://filmotecaclasica.com" class="nav-link">Catálogo</a>
    <a href="/blog/" class="nav-blog">Blog</a>
    <button class="nav-link" id="btn-login-nav" onclick="loginConGoogle()" style="display:none;background:var(--amber);color:#fff;border:none;border-radius:20px;padding:5px 13px;cursor:pointer">Iniciar sesión</button>
    <div class="user-avatar-nav" id="user-avatar-nav" onclick="toggleDropdownNav(event)">
      <span class="av-iniciales"></span>
      <div class="user-dropdown-nav">
        <a class="dd-item-nav" href="/perfil/">👤 Mi perfil</a>
        <div class="dd-divider-nav"></div>
        <div class="dd-item-nav" onclick="cerrarSesion()">↩ Cerrar sesión</div>
      </div>
    </div>
  </div>
</nav>"""


def footer_html():
    return """<footer>
  Filmoteca Clásica · catálogo de cine clásico gratis en YouTube · sin publicidad ·
  <a href="https://github.com/sebadetoma-stack/filmoteca" style="color:var(--text-faint)">código abierto</a>
</footer>"""


def generar_indice(posts, sidebar_html=''):
    """Genera blog/index.html"""
    posts_ord = sorted(posts, key=lambda p: p['meta'].get('fecha',''), reverse=True)

    cards = []
    for p in posts_ord:
        meta = p['meta']
        slug = meta.get('slug','')
        cat = meta.get('categoria','')
        titulo = meta.get('titulo','')
        fecha = formatear_fecha(meta.get('fecha',''))
        imagen = meta.get('imagen','')
        excerpt = p.get('excerpt','')

        if imagen:
            img_html = f'<img src="/blog/imagenes/{imagen}" alt="{titulo}" loading="lazy">'
        else:
            img_html = '<div class="post-img-placeholder">🎬</div>'

        cards.append(f"""<a class="post-card" href="/blog/{slug}/" data-cat="{cat}">
  <div class="post-img">{img_html}</div>
  <div class="post-body">
    <div class="post-cat">{cat}</div>
    <div class="post-title">{titulo}</div>
    <div class="post-excerpt">{excerpt}</div>
    <div class="post-footer">
      <span class="post-meta">SDT · {fecha}</span>
      <span class="leer-mas">Leer más →</span>
    </div>
  </div>
</a>""")

    cats_usadas = list(dict.fromkeys(p['meta'].get('categoria','') for p in posts_ord))
    cat_btns = ''.join(f'<button class="cat-btn" onclick="filtrar(\'{c}\')">{c}</button>' for c in cats_usadas)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blog · Filmoteca Clásica</title>
<meta name="description" content="Artículos sobre cine clásico, directores, géneros e historia del cine.">
<link rel="canonical" href="https://filmotecaclasica.com/blog/">
{GA4}
<style>
{CSS}
{NAV_CSS}
</style>
</head>
<body>
{nav_html()}
<div class="article-layout">
  <div class="article-main">
    <div class="blog-header" style="margin:0 0 1.5rem;padding:0">
      <div class="blog-title">Blog</div>
      <div class="blog-sub">Cine clásico, historia y el proyecto</div>
    </div>
    <div class="cat-filter" style="padding:0;margin-bottom:1.5rem">
      <button class="cat-btn active" onclick="filtrar('')">Todos</button>
      {cat_btns}
    </div>
    <div class="posts-list" id="posts-list" style="padding:0">
{''.join(cards)}
    </div>
  </div>
  {sidebar_html}
</div>
{footer_html()}
<script>
function filtrar(cat) {{
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('.post-card').forEach(c => {{
    c.style.display = (!cat || c.dataset.cat === cat) ? 'flex' : 'none';
  }});
}}
</script>
{FIREBASE_SCRIPT}
</body>
</html>"""
    return html


def generar_articulo(meta, contenido_html, posts_relacionados, sidebar_html=''):
    """Genera HTML de un artículo individual"""
    titulo = meta.get('titulo','')
    cat = meta.get('categoria','')
    fecha = formatear_fecha(meta.get('fecha',''))
    imagen = meta.get('imagen','')
    slug = meta.get('slug','')

    credito = meta.get('credito_imagen', '')
    hero = ''
    if imagen:
        credito_html = f'<div class="article-hero-credito">{credito}</div>' if credito else ''
        hero = f'<div class="article-hero"><img src="/blog/imagenes/{imagen}" alt="{titulo}">{credito_html}</div>'

    # Artículos relacionados
    rel_html = ''
    if posts_relacionados:
        items = []
        for r in posts_relacionados[:3]:
            rm = r['meta']
            r_img = rm.get('imagen','')
            r_slug = rm.get('slug','')
            if r_img:
                r_img_html = f'<img src="/blog/imagenes/{r_img}" alt="{rm.get("titulo","")}">'
            else:
                r_img_html = '🎬'
            items.append(f"""<a class="rel-item" href="/blog/{r_slug}/">
  <div class="rel-img">{r_img_html}</div>
  <div>
    <div class="rel-cat">{rm.get('categoria','')}</div>
    <div class="rel-name">{rm.get('titulo','')}</div>
  </div>
</a>""")
        rel_html = f"""<div class="article-divider"></div>
<div class="rel-titulo">Más artículos de {cat}</div>
<div class="rel-list">{''.join(items)}</div>"""

    schema = f"""{{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "{titulo}",
  "datePublished": "{meta.get('fecha','')}",
  "author": {{"@type": "Person", "name": "Sebastián De Toma"}},
  "publisher": {{"@type": "Organization", "name": "Filmoteca Clásica", "url": "https://filmotecaclasica.com"}},
  "url": "https://filmotecaclasica.com/blog/{slug}/"
}}"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{titulo} · Blog · Filmoteca Clásica</title>
<meta name="description" content="{meta.get('excerpt', titulo)}">
<link rel="canonical" href="https://filmotecaclasica.com/blog/{slug}/">
<meta property="og:title" content="{titulo} · Filmoteca Clásica">
<meta property="og:type" content="article">
{'<meta property="og:image" content="https://filmotecaclasica.com/blog/imagenes/' + imagen + '">' if imagen else ''}
<script type="application/ld+json">{schema}</script>
{GA4}
<style>
{CSS}
{NAV_CSS}
</style>
</head>
<body>
{nav_html()}
{hero}
<div class="article-layout">
  <div class="article-main">
    <div class="article-cat">{cat}</div>
    <h1 class="article-title">{titulo}</h1>
    <div class="article-meta">SDT · {fecha}</div>
    <div class="article-body">{contenido_html}</div>
    {rel_html}
  </div>
  {sidebar_html}
</div>
{footer_html()}
{FIREBASE_SCRIPT}
</body>
</html>"""


def main():
    # Crear carpetas si no existen
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    (BASE / "blog" / "imagenes").mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    (WEB_DIR / "imagenes").mkdir(exist_ok=True)

    # Leer todos los posts
    md_files = sorted(POSTS_DIR.glob("*.md"))
    if not md_files:
        print("No hay posts en blog/posts/. Creá un archivo .md para empezar.")
        print("\nEjemplo de estructura:")
        print("---")
        print("titulo: Mi primer artículo")
        print("categoria: Reseñas")
        print("fecha: 2026-08-18")
        print("imagen: mi-imagen.jpg  # opcional")
        print("slug: mi-primer-articulo")
        print("---")
        print("Contenido del artículo...")
        return

    posts = []
    for f in md_files:
        try:
            meta, html = parsear_md(f)
            # Extraer excerpt (primer párrafo de texto plano)
            texto_plano = re.sub(r'<[^>]+>', '', html)
            excerpt = ' '.join(texto_plano.split()[:30]) + '...'
            meta['excerpt'] = excerpt
            posts.append({'meta': meta, 'html': html, 'excerpt': excerpt, 'archivo': f})
            print(f"  ✓ {meta.get('titulo','?')}")
        except Exception as e:
            print(f"  ✗ Error en {f.name}: {e}")

    if not posts:
        print("No se pudo procesar ningún post.")
        return

    # Copiar imágenes
    img_src = BASE / "blog" / "imagenes"
    img_dst = WEB_DIR / "imagenes"
    if img_src.exists():
        for img in img_src.iterdir():
            shutil.copy2(img, img_dst / img.name)

    # Consultar GA4 para el sidebar (una sola vez)
    print("\nConsultando GA4 para el sidebar...")
    sidebar_html = ''
    peliculas_sidebar = []
    slugs_vistas = obtener_mas_vistas()
    peliculas_sidebar = obtener_datos_peliculas(slugs_vistas)
    sidebar_html = generar_sidebar_html(peliculas_sidebar)
    if peliculas_sidebar:
        print(f"  Sidebar: {len(peliculas_sidebar)} películas obtenidas")
    else:
        print("  Sidebar: sin datos, se omite")

    # Generar índice
    indice = generar_indice(posts, sidebar_html)
    (WEB_DIR / "index.html").write_text(indice, encoding='utf-8')
    print(f"\nÍndice: filmoteca-web/blog/index.html")

    # Generar artículos
    posts_ord = sorted(posts, key=lambda p: p['meta'].get('fecha',''), reverse=True)
    for p in posts_ord:
        slug = p['meta'].get('slug','')
        if not slug:
            print(f"  ✗ Falta slug en {p['archivo'].name}")
            continue
        cat = p['meta'].get('categoria','')
        relacionados = [r for r in posts_ord if r['meta'].get('categoria') == cat and r['meta'].get('slug') != slug]
        art_dir = WEB_DIR / slug
        art_dir.mkdir(exist_ok=True)
        html = generar_articulo(p['meta'], p['html'], relacionados, sidebar_html)
        (art_dir / "index.html").write_text(html, encoding='utf-8')
        print(f"  Artículo: filmoteca-web/blog/{slug}/index.html")

    print(f"\n✓ {len(posts)} artículo(s) generado(s)")
    print("Próximos pasos:")
    print("  1. Copiá filmoteca-web/blog/ a tu repo")
    print("  2. git add blog/ && git commit -m 'blog: ...' && git push")


if __name__ == "__main__":
    main()
