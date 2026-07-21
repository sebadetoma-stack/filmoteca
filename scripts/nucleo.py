"""
Núcleo de la filmoteca: normalización de títulos, similitud difusa,
parseo de duraciones y scoring de coincidencias.

Solo stdlib. Sin dependencias que instalar.

LÓGICA DE DECISIÓN (tres pasadas):
  1. VETOS: trailer/reseña/recopilación, año que choca, dura <55min.
  2. FRASE: el título del catálogo aparece CONTIGUO en el título del video.
     Es la señal más confiable que existe (validada con revisión humana).
     Frase + duración plausible (>=72% del metraje) -> confirmada.
     Frase + duración dudosa (55-72%) -> pendiente (posible copia mutilada).
  3. SCORE: sin frase, el listón es alto. Confirmar solo con título fuerte
     Y duración exacta. Lo demás: pendiente si es plausible, rechazo si no.
"""
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "datos" / "filmoteca.db"

# ---------------------------------------------------------------
# CUOTA
# ---------------------------------------------------------------
LIMITE_UNIDADES = 10_000
LIMITE_BUSQUEDAS = 100

COSTO = {
    "search": 0,
    "playlistItems": 1,
    "videos": 1,
    "channels": 1,
    "playlists": 1,
}


def hoy_pt() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")


class Cuota:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.dia = hoy_pt()
        con.execute("INSERT OR IGNORE INTO cuota(fecha_pt) VALUES (?)", (self.dia,))
        con.commit()

    def _leer(self):
        r = self.con.execute(
            "SELECT unidades, busquedas FROM cuota WHERE fecha_pt = ?", (self.dia,)
        ).fetchone()
        return (r[0], r[1]) if r else (0, 0)

    def gastar(self, metodo: str, n: int = 1) -> bool:
        unidades, busquedas = self._leer()
        if metodo == "search":
            if busquedas + n > LIMITE_BUSQUEDAS:
                return False
            self.con.execute(
                "UPDATE cuota SET busquedas = busquedas + ? WHERE fecha_pt = ?",
                (n, self.dia),
            )
        else:
            costo = COSTO.get(metodo, 1) * n
            if unidades + costo > LIMITE_UNIDADES:
                return False
            self.con.execute(
                "UPDATE cuota SET unidades = unidades + ? WHERE fecha_pt = ?",
                (costo, self.dia),
            )
        self.con.commit()
        return True

    def restante(self):
        u, b = self._leer()
        return {"unidades": LIMITE_UNIDADES - u, "busquedas": LIMITE_BUSQUEDAS - b}


# ---------------------------------------------------------------
# NORMALIZACIÓN
# ---------------------------------------------------------------

RUIDO = re.compile(
    r"\b("
    r"full\s+movie|full\s+length|complete\s+movie|entire\s+movie|"
    r"free\s+movie|movie\s+free|full\s+film|"
    r"pelicula\s+completa|peli\s+completa|filme\s+completo|"
    r"castellano\s+latino|espanol\s+latino|latino|castellano|subtitulada|"
    r"subtitulos|subtitles|english\s+subtitles|"
    r"hd|full\s*hd|1080p?|720p?|4k|remastered|remasterizada|colorized|"
    r"restored|restaurada|widescreen|"
    r"classic\s+movie|clasico|cine\s+clasico|"
    r"public\s+domain|dominio\s+publico|"
    r"western|film\s+noir|drama|comedy|comedia"
    r")\b",
    re.I,
)

NEGATIVAS = re.compile(
    r"\b("
    r"trailer|trailers|tr[aá]iler|teaser|clip|clips|scene|escena|"
    r"review|rese[nñ]a|an[aá]lisis|analysis|reaction|reacci[oó]n|"
    r"soundtrack|ost|score|theme|banda\s+sonora|"
    r"behind\s+the\s+scenes|making\s+of|bloopers|outtakes|"
    r"interview|entrevista|documentary\s+about|"
    r"top\s+\d+|best\s+of|compilation|recopilaci[oó]n|"
    r"marathon|marat[oó]n|double\s+feature|\d+\s+movies|\d+\s+pel[ií]culas|"
    r"\d+\s+hours?\s+of|back\s+to\s+back|"
    r"explained|explicada|ending|final\s+explicado|"
    r"opening|intro|credits|cr[eé]ditos|"
    r"episode|episodio|cap[ií]tulo|part\s+\d+\s+of|parte\s+\d+\s+de|"
    r"colorization\s+test|comparison|comparaci[oó]n|"
    r"shorts?|tiktok"
    r")\b",
    re.I,
)

ROMANOS = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
}

ARTICULOS = {
    "the", "a", "an", "el", "la", "los", "las", "un", "una", "unos", "unas",
    "le", "les", "il", "lo", "der", "die", "das", "l", "de", "of", "y", "and",
}

_ANIO_TOKEN = re.compile(r"^(18|19|20)\d{2}$")


def sin_acentos(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def normalizar(titulo: str, quitar_ruido: bool = False) -> str:
    if not titulo:
        return ""
    s = sin_acentos(titulo).lower()
    if quitar_ruido:
        s = RUIDO.sub(" ", s)
    s = re.sub(r"[\(\[\{]\s*(18|19|20)\d{2}\s*[\)\]\}]", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Acrónimos: "d o a" -> "doa"
    s = re.sub(r"\b(?:\w\s){1,}\w\b", lambda m: m.group(0).replace(" ", ""), s)
    partes = [ROMANOS.get(w, w) for w in s.split()]
    return " ".join(partes)


def tokens_clave(titulo_norm: str) -> set:
    """Tokens sin artículos, conectores ni años sueltos."""
    toks = [w for w in titulo_norm.split()
            if w not in ARTICULOS and not _ANIO_TOKEN.match(w)]
    largos = {w for w in toks if len(w) > 1}
    return largos or set(toks)


def frase_en_video(titulo_cat_norm: str, titulo_vid_norm: str) -> bool:
    """
    ¿El título del catálogo aparece como FRASE CONTIGUA en el del video?
    Es la señal más fuerte: los que suben películas escriben el título
    de corrido ("1935 - This Woman Is Mine - A savage drama...").

    Los tokens sueltos compartidos NO cuentan: "Monster from the Moon"
    comparte 'from' y 'moon' con otros títulos pero no es frase de ninguno.

    Guardas para títulos cortos: un título de una sola palabra corta
    ("M", "Z", "Gilda") solo cuenta si es palabra de 4+ letras o si
    el título entero del video ES ese título.
    """
    if not titulo_cat_norm or not titulo_vid_norm:
        return False
    if titulo_cat_norm == titulo_vid_norm:
        return True
    n_tokens = len(titulo_cat_norm.split())
    if n_tokens == 1 and len(titulo_cat_norm) < 2:
        return False  # demasiado corto para frase confiable (solo "M", "Z")

    # Para títulos de 1 token clave (ej: "Gilda", "Detour", "M"),
    # el video no debe tener muchos tokens clave adicionales — si los tiene,
    # probablemente el token es solo parte de un título más largo.
    # "bridge" en "bridge of san luis rey" tiene 4 tokens clave extra: rechazar.
    # "gilda" en "gilda 1946 rita hayworth full" tiene 0 tokens clave extra: OK.
    # Usamos tokens_clave para no contar artículos ni conectores.
    _vid_key = tokens_clave(titulo_vid_norm)
    _cat_key = tokens_clave(titulo_cat_norm)
    if len(_cat_key) <= 1:
        extra = _vid_key - _cat_key
        if len(extra) >= 4:
            return False

    # Agregar espacios centinela al inicio y fin para capturar matches
    # en los extremos de la cadena (ej: "doa edmond..." empieza con "doa")
    haystack = f" {titulo_vid_norm} "
    needle = f" {titulo_cat_norm} "
    return needle in haystack


def similitud(a: str, b: str) -> float:
    """
    0-100. Ratio de secuencia + cobertura de tokens.
    La regla de 'contenido' (tokens del catálogo dentro del video) se
    ESCALONA por cantidad de tokens: con 1-2 tokens sueltos ya no regala
    95 puntos, porque eso generaba falsos positivos con AKAs cortos.
    """
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio() * 100

    ta, tb = tokens_clave(a), tokens_clave(b)
    if not ta or not tb:
        return seq

    inter = ta & tb
    corto, largo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    cobertura = len(inter) / len(corto) * 100

    if corto <= largo:
        n = len(corto)
        contenido = 70.0 if n == 1 else (85.0 if n == 2 else 95.0)
    else:
        contenido = 0.0

    return max(seq, cobertura * 0.9, contenido)


# ---------------------------------------------------------------
# DURACIONES
# ---------------------------------------------------------------
_ISO = re.compile(
    r"P(?:(?P<d>\d+)D)?T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?"
)


def iso_a_segundos(iso: str) -> int:
    if not iso:
        return 0
    m = _ISO.fullmatch(iso.strip())
    if not m:
        return 0
    g = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    return g["d"] * 86400 + g["h"] * 3600 + g["m"] * 60 + g["s"]


DUR_MINIMA_SEG = 55 * 60
TOLERANCIA = 0.20

# Rangos de plausibilidad del ratio video/IMDb (validados con revisión humana:
# las copias al 72-80% suelen ser versiones TV legítimas).
RATIO_OK = (0.72, 1.30)      # plausible: versión TV, corte europeo, PAL speedup
RATIO_DUDOSO = (0.55, 0.72)  # posiblemente mutilada: a revisión


def score_duracion(imdb_min, yt_seg) -> tuple[float, str]:
    if not yt_seg:
        return 0.0, "sin_duracion_yt"
    if yt_seg < DUR_MINIMA_SEG:
        return 0.0, f"muy_corto ({yt_seg // 60}min)"
    if not imdb_min:
        return 50.0, "sin_duracion_imdb"

    esperado = imdb_min * 60
    ratio = yt_seg / esperado
    delta = abs(1 - ratio)

    if delta <= TOLERANCIA:
        return 100.0, f"calza ({delta:.0%})"
    if RATIO_OK[0] <= ratio <= RATIO_OK[1]:
        return 80.0, f"version corta plausible ({ratio:.0%})"
    if RATIO_DUDOSO[0] <= ratio < RATIO_DUDOSO[1]:
        return 40.0, f"posible copia mutilada ({ratio:.0%})"
    if ratio > 1.6:
        return 5.0, f"dura demasiado ({ratio:.1f}x) - posible recopilacion"
    return 15.0, f"no calza ({ratio:.0%})"


def _dur_plausible(imdb_min, yt_seg):
    """
    Devuelve 'ok' | 'dudosa' | 'no'.
    'ok': suficiente para confirmar si el título es frase.
    """
    if not yt_seg or yt_seg < DUR_MINIMA_SEG:
        return "no"
    if not imdb_min:
        return "ok"  # IMDb no sabe cuánto dura; que sea largometraje alcanza
    ratio = yt_seg / (imdb_min * 60)
    if RATIO_OK[0] <= ratio <= RATIO_OK[1]:
        return "ok"
    if RATIO_DUDOSO[0] <= ratio < RATIO_DUDOSO[1]:
        return "dudosa"
    return "no"


# ---------------------------------------------------------------
# SCORING GLOBAL
# ---------------------------------------------------------------
UMBRAL_CONFIRMADA = 82
UMBRAL_PENDIENTE = 60


def puntuar(pelicula: dict, video: dict, titulos: list[str],
            confianza_canal: int = 50,
            titulos_frase: list[str] | None = None) -> dict:
    """
    titulos:       todos los títulos conocidos (para score difuso).
    titulos_frase: solo los títulos en inglés/español/sin idioma (para match de frase).
                   Si es None, se usa titulos completo (comportamiento anterior).
    """
    tv_raw = video.get("titulo", "")
    tv = normalizar(tv_raw, quitar_ruido=True)
    tv_sin_limpiar = normalizar(tv_raw, quitar_ruido=False)

    # --- PASADA 1: señales para vetos ---
    negativa = bool(NEGATIVAS.search(sin_acentos(tv_raw)))

    anio = pelicula.get("anio")
    anios_vid = [int(a) for a in re.findall(r"\b(19\d{2}|20\d{2})\b", tv_raw)]
    anio_choca = False
    if anios_vid and anio:
        if any(abs(a - anio) <= 1 for a in anios_vid):
            s_anio = 100.0
        else:
            s_anio = 0.0
            anio_choca = True
    else:
        s_anio = 50.0

    yt_seg = video.get("duracion_seg")
    imdb_min = pelicula.get("duracion_min")
    s_dur, motivo_dur = score_duracion(imdb_min, yt_seg)
    ratio = (yt_seg / (imdb_min * 60)) if (yt_seg and imdb_min) else None
    plausible = _dur_plausible(imdb_min, yt_seg)

    vetos = []
    if negativa:
        vetos.append("palabra_negativa")
    if yt_seg and yt_seg < DUR_MINIMA_SEG:
        vetos.append(f"dura_{yt_seg // 60}min")
    if ratio and ratio > 1.6:
        vetos.append(f"dura_{ratio:.1f}x_recopilacion")
    if anio_choca:
        vetos.append(f"anio_declarado_{anios_vid[0]}_vs_{anio}")

    # --- PASADA 2: frase + mejor similitud, contra TODOS los títulos ---
    mejor, cual, frase, frase_con = 0.0, "", False, ""
    # Títulos habilitados para match de frase: inglés/español o sin idioma.
    # Los títulos en otros idiomas (it, fr, de...) solo participan en el score difuso,
    # no en la confirmación por frase. Evita casos como "La Strada" -> "Street Corner".
    _t_frase = titulos_frase if titulos_frase is not None else titulos
    for t in titulos:
        tn = normalizar(t)
        if not tn:
            continue
        s = similitud(tn, tv)
        if s > mejor:
            mejor, cual = s, t
        # la frase se chequea contra el título del video CON y SIN limpiar,
        # pero SOLO con títulos en idiomas permitidos
        if not frase and t in _t_frase:
            if frase_en_video(tn, tv) or frase_en_video(tn, tv_sin_limpiar):
                frase, frase_con = True, t

    # --- score ponderado (para ranking entre candidatos y para el fallback) ---
    score = (
        mejor * 0.50 +
        s_dur * 0.33 +
        s_anio * 0.09 +
        confianza_canal * 0.08
    )
    if frase:
        score = max(score, 85.0)  # la frase domina el ranking entre candidatos
    score = max(0.0, min(100.0, score))

    # --- PASADA 3: decisión ---
    if vetos:
        score = min(score, 25.0)
        estado = "rechazada"
    elif frase and plausible == "ok" and not anio_choca:
        estado = "confirmada"
    elif frase and plausible == "dudosa":
        estado = "pendiente"      # el título es la peli, pero puede estar mutilada
    elif s_dur >= 100.0 and mejor >= 88.0:
        # Título fuerte + duración exacta.
        # Si el título que matcheó tiene solo 1 token clave (ej: "The Road",
        # "The Street"), exigir similitud más alta para evitar falsos positivos.
        _n_tokens_cual = len(tokens_clave(normalizar(cual)))
        if _n_tokens_cual >= 2 or mejor >= 95.0:
            estado = "confirmada"
        else:
            estado = "pendiente"
    elif score >= UMBRAL_PENDIENTE and mejor >= 55.0:
        estado = "pendiente"
    else:
        estado = "rechazada"

    senales = {
        "titulo": round(mejor, 1),
        "match_con": cual,
        "frase": frase,
        "frase_con": frase_con,
        "duracion": round(s_dur, 1),
        "dur_motivo": motivo_dur,
        "anio": s_anio,
        "canal": confianza_canal,
        "vetos": vetos,
    }
    return {"score": round(score, 1), "estado": estado,
            "senales": json.dumps(senales, ensure_ascii=False)}


# ---------------------------------------------------------------
# GEOBLOQUEO
# ---------------------------------------------------------------
def evaluar_region(allowed, blocked, pais="AR"):
    if allowed:
        lista = allowed if isinstance(allowed, list) else allowed.split(",")
        return 1 if pais in [x.strip() for x in lista] else 0
    if blocked:
        lista = blocked if isinstance(blocked, list) else blocked.split(",")
        return 0 if pais in [x.strip() for x in lista] else 1
    return None


def conectar(path=DB) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con
