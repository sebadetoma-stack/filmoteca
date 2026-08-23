"""
traducir_gemini.py
Filmoteca Clásica — Valida títulos y traduce sinopsis con Gemini.

Lee para_gemini.json y por cada registro:
- Si titulo_orig ya está en español → lo usa directamente
- Si necesita traducir título → pregunta a Gemini si tiene traducción canónica
- Si necesita traducir sinopsis → Gemini traduce al español argentino

Genera traducidos_gemini.json con todos los resultados.
Muestra progreso uno por uno.

Uso:
    $env:GEMINI_API_KEY="tu_clave"
    python traducir_gemini.py
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

try:
    from langdetect import detect
except ImportError:
    sys.exit("Falta langdetect. Corré: pip install langdetect")

SCRIPTS_DIR  = Path(__file__).resolve().parent
JSON_ENTRADA = SCRIPTS_DIR / "pendientes_gemini.json"
JSON_SALIDA  = SCRIPTS_DIR / "traducidos_gemini.json"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_KEY:
    sys.exit("ERROR: Falta GEMINI_API_KEY")

PAUSA = 0.5


# ── Detección de idioma ───────────────────────────────────────────────────────

def es_español(texto):
    if not texto or len(texto.strip()) < 3:
        return False
    try:
        return detect(texto) == "es"
    except Exception:
        return False


# ── Gemini ────────────────────────────────────────────────────────────────────

def llamar_gemini(prompt):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 400, "temperature": 0.1},
    }).encode("utf-8")

    url = f"{GEMINI_URL}?key={GEMINI_KEY}"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"    [!] Error Gemini: {e}")
        return None


def validar_o_traducir_titulo(titulo_primario, titulo_orig, anio):
    prompt = (
        f'La película "{titulo_primario}" ({anio}, título original: "{titulo_orig}") '
        f'¿tiene una traducción canónica al español? '
        f'Si sí, devolvé solo el título en español. '
        f'Si no tiene traducción establecida o se usa igual en español, '
        f'devolvé el título original sin cambios. '
        f'Solo el título, sin explicaciones ni comillas.'
    )
    return llamar_gemini(prompt)


def traducir_sinopsis(sinopsis, titulo_ref):
    prompt = (
        f'Traducí al español argentino esta sinopsis de la película "{titulo_ref}":\n\n'
        f'{sinopsis}\n\n'
        f'Devolvé SOLO la traducción, sin explicaciones ni comillas.'
    )
    return llamar_gemini(prompt)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    data = json.loads(JSON_ENTRADA.read_text(encoding="utf-8"))
    total = len(data)

    print(f"Procesando {total:,} registros...\n")

    resultados = []
    cnt_orig_es   = 0  # titulo_orig ya en español
    cnt_gemini_t  = 0  # título traducido por Gemini
    cnt_gemini_s  = 0  # sinopsis traducida por Gemini
    cnt_errores   = 0

    for i, p in enumerate(data, 1):
        tconst          = p["tconst"]
        titulo_primario = p["titulo_primario"]
        titulo_orig     = p.get("titulo_orig") or ""
        anio            = p["anio"]
        entry           = dict(p)

        print(f"  [{i}/{total}] {titulo_primario} ({anio})")

        # ── Título ────────────────────────────────────────────────────────────
        if "traducir_titulo" in p:
            # Antes de Gemini: ¿titulo_orig ya está en español?
            if titulo_orig and es_español(titulo_orig):
                entry["titulo_es_resuelto"] = titulo_orig
                entry["fuente_titulo"]       = "titulo_orig_es"
                entry.pop("traducir_titulo", None)
                cnt_orig_es += 1
                print(f"    → título: '{titulo_orig}' (original ya en español)")
            else:
                resultado = validar_o_traducir_titulo(titulo_primario, titulo_orig, anio)
                time.sleep(PAUSA)
                if resultado:
                    entry["titulo_es_resuelto"] = resultado
                    entry["fuente_titulo"]       = "gemini"
                    entry.pop("traducir_titulo", None)
                    cnt_gemini_t += 1
                    print(f"    → título: '{resultado}' (Gemini)")
                else:
                    entry["fuente_titulo"] = "error"
                    cnt_errores += 1
                    print(f"    → título: ERROR")

        # ── Sinopsis ──────────────────────────────────────────────────────────
        if "traducir_sinopsis" in p:
            titulo_ref = entry.get("titulo_es_resuelto") or titulo_primario
            resultado = traducir_sinopsis(p["traducir_sinopsis"], titulo_ref)
            time.sleep(PAUSA)
            if resultado:
                entry["sinopsis_es_resuelta"] = resultado
                entry["fuente_sinopsis"]       = "gemini"
                entry.pop("traducir_sinopsis", None)
                cnt_gemini_s += 1
                print(f"    → sinopsis: traducida ({len(resultado)} chars)")
            else:
                entry["fuente_sinopsis"] = "error"
                cnt_errores += 1
                print(f"    → sinopsis: ERROR")

        resultados.append(entry)

        # Guardar cada 100 para no perder progreso
        if i % 100 == 0:
            JSON_SALIDA.write_text(
                json.dumps(resultados, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"  ── checkpoint guardado ({i}/{total}) ──")

    # Guardar final
    JSON_SALIDA.write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"  Total procesados:              {total:,}")
    print(f"  Títulos desde original ES:     {cnt_orig_es:,}")
    print(f"  Títulos traducidos por Gemini: {cnt_gemini_t:,}")
    print(f"  Sinopsis traducidas (Gemini):  {cnt_gemini_s:,}")
    print(f"  Errores:                       {cnt_errores:,}")
    print(f"\n  JSON guardado en: {JSON_SALIDA}")


if __name__ == "__main__":
    main()
