"""
reprocesar_errores_gemini.py
Filmoteca Clásica — Reprocesa los registros que fallaron en traducir_gemini.py

Lee traducidos_gemini.json, busca los que tienen fuente 'error',
los reprocesa con Gemini y actualiza el JSON.

Uso:
    $env:GEMINI_API_KEY="tu_clave"
    python reprocesar_errores_gemini.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
JSON_PATH   = SCRIPTS_DIR / "traducidos_gemini.json"
GEMINI_URL  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_KEY:
    sys.exit("ERROR: Falta GEMINI_API_KEY")

PAUSA = 1.0


# ── Gemini ────────────────────────────────────────────────────────────────────

def llamar_gemini(prompt, reintentos=3):
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
    for intento in range(1, reintentos + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            print(f"    [!] Intento {intento}/{reintentos} falló: {e}")
            if intento < reintentos:
                time.sleep(5)
    return None


def traducir_titulo(titulo_primario, titulo_orig, anio):
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
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    errores = [
        (i, p) for i, p in enumerate(data)
        if p.get("fuente_titulo") == "error" or p.get("fuente_sinopsis") == "error"
    ]

    print(f"Registros con error: {len(errores)}")
    if not errores:
        print("Nada para reprocesar.")
        return

    resueltos  = 0
    pendientes = 0

    for i, (idx, p) in enumerate(errores, 1):
        titulo_primario = p["titulo_primario"]
        titulo_orig     = p.get("titulo_orig") or ""
        anio            = p["anio"]

        print(f"  [{i}/{len(errores)}] {titulo_primario} ({anio})")

        # Título
        if p.get("fuente_titulo") == "error" and "traducir_titulo" in p:
            resultado = traducir_titulo(titulo_primario, titulo_orig, anio)
            time.sleep(PAUSA)
            if resultado:
                data[idx]["titulo_es_resuelto"] = resultado
                data[idx]["fuente_titulo"]       = "gemini"
                data[idx].pop("traducir_titulo", None)
                resueltos += 1
                print(f"    → título: '{resultado}'")
            else:
                pendientes += 1
                print(f"    → título: sigue fallando")

        # Sinopsis
        if p.get("fuente_sinopsis") == "error" and "traducir_sinopsis" in p:
            titulo_ref = p.get("titulo_es_resuelto") or titulo_primario
            resultado  = traducir_sinopsis(p["traducir_sinopsis"], titulo_ref)
            time.sleep(PAUSA)
            if resultado:
                data[idx]["sinopsis_es_resuelta"] = resultado
                data[idx]["fuente_sinopsis"]       = "gemini"
                data[idx].pop("traducir_sinopsis", None)
                resueltos += 1
                print(f"    → sinopsis: traducida ({len(resultado)} chars)")
            else:
                pendientes += 1
                print(f"    → sinopsis: sigue fallando")

    # Guardar
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"  Resueltos:         {resueltos}")
    print(f"  Siguen fallando:   {pendientes}")
    print(f"  JSON actualizado: {JSON_PATH}")


if __name__ == "__main__":
    main()
