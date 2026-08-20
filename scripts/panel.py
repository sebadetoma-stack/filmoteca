"""
panel.py — Filmoteca Clásica Admin Panel
Flask local, corre en http://127.0.0.1:5000

Uso:
    cd C:\\Users\\sebad\\Downloads\\filmoteca\\scripts
    $env:YT_API_KEY="..."
    $env:ANTHROPIC_API_KEY="..."
    $env:TMDB_API_KEY="..."
    python panel.py
"""

import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

# ── Rutas ─────────────────────────────────────────────────────────────────────

SCRIPTS_DIR = Path(__file__).resolve().parent
BASE_DIR    = SCRIPTS_DIR.parent
DB_PATH     = BASE_DIR / "datos" / "filmoteca.db"
CSV_SEMILLA = BASE_DIR / "datos" / "canales_semilla.csv"

app = Flask(__name__, template_folder=str(SCRIPTS_DIR / "templates"))

# ── API Keys en RAM ───────────────────────────────────────────────────────────

KEYS = {
    "YT_API_KEY":        os.environ.get("YT_API_KEY", ""),
    "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
    "TMDB_API_KEY":      os.environ.get("TMDB_API_KEY", ""),
}

# ── Cola de log para SSE ──────────────────────────────────────────────────────

log_queue: queue.Queue = queue.Queue()
task_running = threading.Event()


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    log_queue.put(f"[{ts}] {msg}")


# ── DB helpers ─────────────────────────────────────────────────────────────────

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def get_estado():
    con = db()
    try:
        confirmadas = con.execute(
            "SELECT COUNT(DISTINCT tconst) FROM coincidencias WHERE estado='confirmada'"
        ).fetchone()[0]
        pendientes = con.execute(
            "SELECT COUNT(*) FROM coincidencias WHERE estado='pendiente'"
        ).fetchone()[0]
        sin_poster = con.execute("""
            SELECT COUNT(DISTINCT p.tconst) FROM peliculas p
            JOIN coincidencias co ON co.tconst = p.tconst
            WHERE co.estado='confirmada' AND p.poster_url IS NULL
        """).fetchone()[0]
        sin_pais = con.execute("""
            SELECT COUNT(DISTINCT p.tconst) FROM peliculas p
            JOIN coincidencias co ON co.tconst = p.tconst
            WHERE co.estado='confirmada' AND (p.pais IS NULL OR p.pais='')
        """).fetchone()[0]
        sin_sinopsis = con.execute("""
            SELECT COUNT(DISTINCT p.tconst) FROM peliculas p
            JOIN coincidencias co ON co.tconst = p.tconst
            WHERE co.estado='confirmada' AND (p.sinopsis IS NULL OR p.sinopsis='')
        """).fetchone()[0]
        videos_nuevos = con.execute("""
            SELECT COUNT(*) FROM videos v
            WHERE v.activo = 1
              AND v.duracion_seg >= 3300
              AND NOT EXISTS (
                SELECT 1 FROM coincidencias co WHERE co.video_id = v.video_id
              )
        """).fetchone()[0]
        return {
            "confirmadas":  confirmadas,
            "pendientes":   pendientes,
            "sin_poster":   sin_poster,
            "sin_pais":     sin_pais,
            "sin_sinopsis": sin_sinopsis,
            "videos_nuevos": videos_nuevos,
        }
    finally:
        con.close()


def get_canales():
    con = db()
    try:
        canales = con.execute("""
            SELECT c.channel_id, c.nombre, c.capa, c.confianza,
                   c.ultima_cosecha, c.total_videos,
                   COUNT(CASE WHEN v.activo=1 AND v.duracion_seg>=3300 THEN 1 END) as largos,
                   COUNT(CASE WHEN v.activo=1 AND NOT EXISTS(
                       SELECT 1 FROM coincidencias co WHERE co.video_id=v.video_id
                   ) AND v.duracion_seg>=3300 THEN 1 END) as sin_procesar
            FROM canales c
            LEFT JOIN videos v ON v.channel_id = c.channel_id
            WHERE c.confianza > 0
            GROUP BY c.channel_id
            ORDER BY c.confianza DESC, c.nombre
        """).fetchall()
        resultado = []
        ahora = datetime.now(timezone.utc)
        for c in canales:
            ultima = c["ultima_cosecha"]
            if ultima:
                try:
                    dt = datetime.fromisoformat(ultima.replace("Z", "+00:00"))
                    dias = (ahora - dt).days
                except Exception:
                    dias = None
            else:
                dias = None

            if dias is None:
                freshness = "nunca"
                color = "rojo"
            elif dias > 30:
                freshness = f"{dias}d"
                color = "amarillo"
            else:
                freshness = f"{dias}d"
                color = "verde"

            resultado.append({
                "channel_id":   c["channel_id"],
                "nombre":       c["nombre"],
                "capa":         c["capa"],
                "confianza":    c["confianza"],
                "total_videos": c["total_videos"] or 0,
                "largos":       c["largos"] or 0,
                "sin_procesar": c["sin_procesar"] or 0,
                "ultima_cosecha": freshness,
                "color":        color,
            })
        return resultado
    finally:
        con.close()


# ── Ejecutor de scripts en background ────────────────────────────────────────

def run_script(cmd: list, env_extra: dict = None):
    """Corre un script en background y emite su stdout al log."""
    if task_running.is_set():
        log("⚠ Ya hay una tarea en curso. Esperá a que termine.")
        return

    def _run():
        task_running.set()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)
        env.update({k: v for k, v in KEYS.items() if v})

        log(f"▶ {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(
                [sys.executable] + cmd,
                cwd=str(SCRIPTS_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in proc.stdout:
                log(line.rstrip())
            proc.wait()
            log(f"✓ Proceso terminado (código {proc.returncode})")
        except Exception as e:
            log(f"✗ Error: {e}")
        finally:
            task_running.clear()

    threading.Thread(target=_run, daemon=True).start()


# ── Rutas ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("panel.html")


@app.route("/api/estado")
def api_estado():
    return jsonify(get_estado())


@app.route("/api/canales")
def api_canales():
    return jsonify(get_canales())


@app.route("/api/keys", methods=["POST"])
def api_keys():
    data = request.json or {}
    for k in ("YT_API_KEY", "ANTHROPIC_API_KEY", "TMDB_API_KEY"):
        if data.get(k):
            KEYS[k] = data[k]
    return jsonify({"ok": True, "keys": {k: bool(v) for k, v in KEYS.items()}})


@app.route("/api/keys/status")
def api_keys_status():
    return jsonify({k: bool(v) for k, v in KEYS.items()})


@app.route("/api/running")
def api_running():
    return jsonify({"running": task_running.is_set()})


# ── Pipeline ──────────────────────────────────────────────────────────────────

@app.route("/api/run/cosechar", methods=["POST"])
def run_cosechar():
    run_script(["02_cosechar.py"])
    return jsonify({"ok": True})


@app.route("/api/run/cosechar_canal", methods=["POST"])
def run_cosechar_canal():
    channel_id = request.json.get("channel_id", "")
    if not channel_id:
        return jsonify({"ok": False, "error": "Falta channel_id"})
    run_script(["02_cosechar.py", "--canal", channel_id])
    return jsonify({"ok": True})


@app.route("/api/run/matching", methods=["POST"])
def run_matching():
    run_script(["03_matching.py"])
    return jsonify({"ok": True})


@app.route("/api/run/resolver", methods=["POST"])
def run_resolver():
    run_script(["ia_resolver2.py", "--pendientes"])
    return jsonify({"ok": True})


@app.route("/api/run/aplicar", methods=["POST"])
def run_aplicar():
    # ia_resolver2.py genera ia_decisiones2.json en scripts/
    json_path = SCRIPTS_DIR / "ia_decisiones2.json"
    if not json_path.exists():
        return jsonify({"ok": False, "error": "No existe ia_decisiones2.json. Corré Resolver IA primero."})
    run_script(["aplicar_decisiones.py", str(json_path)])
    return jsonify({"ok": True})


@app.route("/api/run/auditar", methods=["POST"])
def run_auditar():
    score = request.json.get("score", 85)
    run_script(["ia_auditar.py", "--score", str(score)])
    return jsonify({"ok": True})


@app.route("/api/run/tmdb", methods=["POST"])
def run_tmdb():
    run_script(["enriquecer_tmdb.py"])
    return jsonify({"ok": True})


@app.route("/api/run/paises", methods=["POST"])
def run_paises():
    run_script(["enriquecer_paises.py"])
    return jsonify({"ok": True})


@app.route("/api/run/paginas", methods=["POST"])
def run_paginas():
    run_script(["generar_paginas.py"])
    return jsonify({"ok": True})


# ── Canales ───────────────────────────────────────────────────────────────────

@app.route("/api/canal/agregar", methods=["POST"])
def canal_agregar():
    """Resuelve handle/ID, agrega al CSV y corre --semilla."""
    handle = (request.json or {}).get("handle", "").strip()
    if not handle:
        return jsonify({"ok": False, "error": "Falta handle"})

    if not KEYS["YT_API_KEY"]:
        return jsonify({"ok": False, "error": "Falta YT_API_KEY"})

    # Resolver handle a channel_id + nombre
    try:
        if handle.startswith("UC"):
            params = urllib.parse.urlencode({"part": "snippet", "id": handle, "key": KEYS["YT_API_KEY"]})
        elif handle.startswith("@"):
            params = urllib.parse.urlencode({"part": "snippet", "forHandle": handle.lstrip("@"), "key": KEYS["YT_API_KEY"]})
        else:
            return jsonify({"ok": False, "error": "Formato inválido. Usá @handle o UCxxx"})

        url = f"https://www.googleapis.com/youtube/v3/channels?{params}"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        items = data.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": f"No se encontró canal: {handle}"})

        channel_id = items[0]["id"]
        nombre = items[0]["snippet"]["title"]
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    # Agregar al CSV si no existe
    csv_text = CSV_SEMILLA.read_text(encoding="utf-8") if CSV_SEMILLA.exists() else "identificador,nombre,capa,confianza,notas\n"
    if channel_id in csv_text or handle in csv_text:
        return jsonify({"ok": False, "error": f"El canal ya está en canales_semilla.csv"})

    linea = f"{channel_id},{nombre},particular,50,Agregado desde panel\n"
    with open(CSV_SEMILLA, "a", encoding="utf-8") as f:
        f.write(linea)

    log(f"Canal agregado al CSV: {nombre} ({channel_id})")

    # Correr --semilla
    run_script(["02_cosechar.py", "--semilla"])
    return jsonify({"ok": True, "nombre": nombre, "channel_id": channel_id})


# ── Reportes ──────────────────────────────────────────────────────────────────

SHEET_ID    = "15UqbWXy4z7OK163Z8mKcST9vd3zLtLahUaSOfApTuYo"
CREDS_PATH  = BASE_DIR / "datos" / "google_credentials.json"


def sheets_sync():
    """Baja reportes de Google Sheets y los inserta en la tabla reportes."""
    try:
        import google.auth
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return {"ok": False, "error": "Falta google-api-python-client. Corré: pip install google-api-python-client google-auth --break-system-packages"}

    if not CREDS_PATH.exists():
        return {"ok": False, "error": f"No se encuentra {CREDS_PATH}"}

    creds = service_account.Credentials.from_service_account_file(
        str(CREDS_PATH),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    service = build("sheets", "v4", credentials=creds)
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="A2:E1000"
    ).execute()
    rows = result.get("values", [])

    con = db()
    nuevos = 0
    for row in rows:
        if len(row) < 3:
            continue
        fecha   = row[0] if len(row) > 0 else ""
        titulo  = row[1] if len(row) > 1 else ""
        video_id = row[2] if len(row) > 2 else ""
        motivo  = row[3] if len(row) > 3 else ""
        detalle = row[4] if len(row) > 4 else ""

        if not video_id:
            continue

        # Buscar tconst por video_id
        row_db = con.execute(
            "SELECT tconst FROM coincidencias WHERE video_id = ?", (video_id,)
        ).fetchone()
        tconst = row_db[0] if row_db else None

        # Insertar solo si no existe
        existing = con.execute(
            "SELECT id FROM reportes WHERE video_id = ?", (video_id,)
        ).fetchone()
        if not existing:
            con.execute(
                "INSERT INTO reportes (video_id, tconst, motivo, detalle, fecha, atendido) VALUES (?,?,?,?,?,0)",
                (video_id, tconst, motivo, detalle, fecha)
            )
            nuevos += 1

    con.commit()
    con.close()
    return {"ok": True, "nuevos": nuevos, "total": len(rows)}


def get_reportes():
    """Devuelve reportes no atendidos con info de la película."""
    con = db()
    rows = con.execute("""
        SELECT r.id, r.video_id, r.tconst, r.motivo, r.detalle, r.fecha,
               p.titulo_primario, p.anio,
               v.titulo as titulo_yt
        FROM reportes r
        LEFT JOIN peliculas p ON p.tconst = r.tconst
        LEFT JOIN videos v ON v.video_id = r.video_id
        WHERE r.atendido = 0
        ORDER BY r.fecha DESC
    """).fetchall()

    resultado = []
    for r in rows:
        # Buscar alternativas confirmadas para el mismo tconst
        alternativas = []
        if r["tconst"]:
            alts = con.execute("""
                SELECT co.video_id, ca.nombre as canal, v.duracion_seg
                FROM coincidencias co
                JOIN videos v ON v.video_id = co.video_id
                LEFT JOIN canales ca ON ca.channel_id = v.channel_id
                WHERE co.tconst = ?
                  AND co.video_id != ?
                  AND co.estado = 'confirmada'
                  AND v.activo = 1
            """, (r["tconst"], r["video_id"])).fetchall()
            alternativas = [dict(a) for a in alts]

        resultado.append({
            "id":          r["id"],
            "video_id":    r["video_id"],
            "tconst":      r["tconst"],
            "motivo":      r["motivo"],
            "detalle":     r["detalle"],
            "fecha":       r["fecha"],
            "titulo":      r["titulo_primario"] or r["titulo_yt"] or r["video_id"],
            "anio":        r["anio"],
            "alternativas": alternativas,
        })
    con.close()
    return resultado


@app.route("/api/reportes/sync", methods=["POST"])
def api_reportes_sync():
    result = sheets_sync()
    return jsonify(result)


@app.route("/api/reportes")
def api_reportes():
    return jsonify(get_reportes())


@app.route("/api/reportes/aplicar", methods=["POST"])
def api_reportes_aplicar():
    """Aplica un video_id nuevo a una coincidencia y marca el reporte como atendido."""
    data       = request.json or {}
    reporte_id = data.get("reporte_id")
    tconst     = data.get("tconst")
    video_id_nuevo = data.get("video_id_nuevo")

    if not all([reporte_id, tconst, video_id_nuevo]):
        return jsonify({"ok": False, "error": "Faltan parámetros"})

    if not KEYS["YT_API_KEY"]:
        return jsonify({"ok": False, "error": "Falta YT_API_KEY"})

    # Verificar que el video nuevo existe y está disponible en AR
    params = urllib.parse.urlencode({
        "part":       "status,contentDetails,snippet",
        "id":         video_id_nuevo,
        "regionCode": "AR",
        "key":        KEYS["YT_API_KEY"],
    })
    url = f"https://www.googleapis.com/youtube/v3/videos?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            vdata = json.loads(r.read())
        items = vdata.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "Video no encontrado en YouTube"})

        item    = items[0]
        stat    = item.get("status", {})
        cd      = item.get("contentDetails", {})
        snip    = item.get("snippet", {})
        blocked = cd.get("regionRestriction", {}).get("blocked", [])
        allowed = cd.get("regionRestriction", {}).get("allowed", [])

        if "AR" in blocked or (allowed and "AR" not in allowed):
            return jsonify({"ok": False, "error": "Video bloqueado en Argentina"})
        if stat.get("privacyStatus") != "public":
            return jsonify({"ok": False, "error": "Video no es público"})

        # Calcular duración
        iso = cd.get("duration", "PT0S")
        h = int(re.search(r'(\d+)H', iso).group(1)) if re.search(r'\d+H', iso) else 0
        m = int(re.search(r'(\d+)M', iso).group(1)) if re.search(r'\d+M', iso) else 0
        s = int(re.search(r'(\d+)S', iso).group(1)) if re.search(r'\d+S', iso) else 0
        dur_seg = h * 3600 + m * 60 + s

        channel_id   = snip.get("channelId", "")
        canal_nombre = snip.get("channelTitle", "")
        titulo_yt    = snip.get("title", "")
        publicado    = snip.get("publishedAt", "")[:10]
        idioma_audio = snip.get("defaultAudioLanguage", None)

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    con = db()
    cols_vid  = {r[1] for r in con.execute("PRAGMA table_info(videos)").fetchall()}
    cols_coin = {r[1] for r in con.execute("PRAGMA table_info(coincidencias)").fetchall()}
    cols_can  = {r[1] for r in con.execute("PRAGMA table_info(canales)").fetchall()}

    # Registrar canal si no existe
    if not con.execute("SELECT 1 FROM canales WHERE channel_id=?", (channel_id,)).fetchone():
        campos_can = {"channel_id": channel_id, "nombre": canal_nombre}
        if "capa"      in cols_can: campos_can["capa"]      = "particular"
        if "confianza" in cols_can: campos_can["confianza"] = 50
        cols_c = ", ".join(campos_can.keys())
        vals_c = ", ".join(["?"] * len(campos_can))
        con.execute(f"INSERT OR IGNORE INTO canales ({cols_c}) VALUES ({vals_c})", list(campos_can.values()))

    # Insertar video
    campos_vid = {"video_id": video_id_nuevo, "channel_id": channel_id}
    if "titulo"        in cols_vid: campos_vid["titulo"]        = titulo_yt
    if "duracion_seg"  in cols_vid: campos_vid["duracion_seg"]  = dur_seg
    if "publicado"     in cols_vid: campos_vid["publicado"]     = publicado
    if "idioma_audio"  in cols_vid and idioma_audio: campos_vid["idioma_audio"] = idioma_audio
    if "ve_ar"         in cols_vid: campos_vid["ve_ar"]         = 1
    if "activo"        in cols_vid: campos_vid["activo"]        = 1
    cols_v = ", ".join(campos_vid.keys())
    vals_v = ", ".join(["?"] * len(campos_vid))
    con.execute(f"INSERT OR IGNORE INTO videos ({cols_v}) VALUES ({vals_v})", list(campos_vid.values()))

    # Insertar coincidencia
    campos_coin = {"tconst": tconst, "video_id": video_id_nuevo}
    if "score"         in cols_coin: campos_coin["score"]         = 99
    if "senales"       in cols_coin: campos_coin["senales"]       = "reemplazo_manual"
    if "estado"        in cols_coin: campos_coin["estado"]        = "confirmada"
    if "verificado_ar" in cols_coin: campos_coin["verificado_ar"] = "ar_ok"
    if "revisado_por"  in cols_coin: campos_coin["revisado_por"]  = "humano"
    if "notas"         in cols_coin: campos_coin["notas"]         = "Reemplazo aplicado desde panel"
    if "creado"        in cols_coin: campos_coin["creado"]        = datetime.now(timezone.utc).isoformat()
    cols_co = ", ".join(campos_coin.keys())
    vals_co = ", ".join(["?"] * len(campos_coin))
    con.execute(f"INSERT OR IGNORE INTO coincidencias ({cols_co}) VALUES ({vals_co})", list(campos_coin.values()))

    # Rechazar coincidencia vieja (el video del reporte)
    video_id_viejo = con.execute(
        "SELECT video_id FROM reportes WHERE id=?", (reporte_id,)
    ).fetchone()
    if video_id_viejo and video_id_viejo[0] != video_id_nuevo:
        con.execute("""
            UPDATE coincidencias SET estado='rechazada', revisado_por='humano'
            WHERE tconst=? AND video_id=?
        """, (tconst, video_id_viejo[0]))

    # Marcar reporte como atendido
    con.execute("UPDATE reportes SET atendido=1 WHERE id=?", (reporte_id,))

    con.commit()
    con.close()

    return jsonify({"ok": True, "titulo_yt": titulo_yt, "duracion_seg": dur_seg})


@app.route("/api/reportes/atender", methods=["POST"])
def api_reportes_atender():
    """Marca un reporte como atendido sin cambiar nada en la DB."""
    reporte_id = (request.json or {}).get("reporte_id")
    if not reporte_id:
        return jsonify({"ok": False, "error": "Falta reporte_id"})
    con = db()
    con.execute("UPDATE reportes SET atendido=1 WHERE id=?", (reporte_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True})


# ── SSE ───────────────────────────────────────────────────────────────────────

@app.route("/api/log/stream")
def log_stream():
    def event_stream():
        while True:
            try:
                msg = log_queue.get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                yield "data: null\n\n"  # keepalive

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  Filmoteca Clásica — Panel de administración")
    print(f"  DB: {DB_PATH}")
    print(f"  Keys cargadas: {', '.join(k for k, v in KEYS.items() if v) or 'ninguna'}")
    print(f"{'='*50}")
    print(f"\n  Abrí http://127.0.0.1:5000 en el navegador\n")
    app.run(debug=False, host="127.0.0.1", port=5000, threaded=True)
