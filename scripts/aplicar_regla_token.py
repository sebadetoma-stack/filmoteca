#!/usr/bin/env python3
"""
Aplica la nueva regla del matcher sobre las confirmadas ya existentes:
si el título tiene 1 token clave y el año NO aparece en el título del video,
baja la coincidencia a pendiente para que la IA la resuelva.

No re-corre el matcher completo. Solo ajusta las confirmadas en riesgo.
"""
import json, re, sqlite3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nucleo import tokens_clave, normalizar

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

filas = con.execute("""
    SELECT co.tconst, co.video_id, co.senales,
           p.titulo_primario, p.anio,
           v.titulo as vtitulo
    FROM coincidencias co
    JOIN peliculas p ON p.tconst = co.tconst
    JOIN videos v ON v.video_id = co.video_id
    WHERE co.estado = 'confirmada'
      AND v.activo = 1
      AND (co.revisado_por != 'humano' OR co.revisado_por IS NULL)
""").fetchall()

bajadas = 0
for r in filas:
    try:
        s = json.loads(r['senales']) if r['senales'] else {}
    except:
        s = {}

    # Solo las que se confirmaron por frase
    if not s.get('frase'):
        continue

    frase_con = s.get('frase_con', r['titulo_primario'])
    n_tokens = len(tokens_clave(normalizar(frase_con)))

    # Si tiene más de 1 token clave, está bien
    if n_tokens > 1:
        continue

    # Verificar si el año aparece en el título del video
    anio = r['anio']
    anios_vid = [int(a) for a in re.findall(r'\b(19\d{2}|20\d{2})\b', r['vtitulo'])]
    if anios_vid and any(abs(a - anio) <= 1 for a in anios_vid):
        continue  # tiene año, está bien

    # Bajar a pendiente
    con.execute(
        "UPDATE coincidencias SET estado='pendiente' WHERE tconst=? AND video_id=?",
        (r['tconst'], r['video_id'])
    )
    bajadas += 1

con.commit()
con.close()
print(f"Bajadas a pendiente: {bajadas}")
print(f"Revisadas: {len(filas)}")
print("\nAhora corré: python3 ia_resolver2.py --pendientes")
