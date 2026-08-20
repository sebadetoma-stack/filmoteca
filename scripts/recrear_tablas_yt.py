import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "datos" / "filmoteca.db"
con = sqlite3.connect(DB)
con.executescript("""
CREATE TABLE IF NOT EXISTS canales (
    channel_id      TEXT PRIMARY KEY,
    uploads_id      TEXT,
    handle          TEXT,
    nombre          TEXT,
    capa            TEXT NOT NULL,
    confianza       INTEGER DEFAULT 50,
    ultima_cosecha  TEXT,
    total_videos    INTEGER,
    notas           TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id        TEXT PRIMARY KEY,
    channel_id      TEXT REFERENCES canales(channel_id),
    titulo          TEXT NOT NULL,
    descripcion     TEXT,
    duracion_seg    INTEGER,
    publicado       TEXT,
    idioma_audio    TEXT,
    subtitulos      INTEGER DEFAULT 0,
    definicion      TEXT,
    region_allowed  TEXT,
    region_blocked  TEXT,
    ve_ar           INTEGER,
    activo          INTEGER DEFAULT 1,
    visto_ultima_vez TEXT,
    caido_desde     TEXT
);

CREATE INDEX IF NOT EXISTS ix_vid_canal  ON videos(channel_id);
CREATE INDEX IF NOT EXISTS ix_vid_activo ON videos(activo);
CREATE INDEX IF NOT EXISTS ix_vid_dur    ON videos(duracion_seg);

CREATE TABLE IF NOT EXISTS coincidencias (
    tconst      TEXT NOT NULL REFERENCES peliculas(tconst) ON DELETE CASCADE,
    video_id    TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    score       REAL NOT NULL,
    senales     TEXT,
    estado      TEXT NOT NULL DEFAULT 'pendiente',
    verificado_ar TEXT DEFAULT 'sin_datos',
    revisado_por TEXT,
    notas       TEXT,
    creado      TEXT,
    PRIMARY KEY (tconst, video_id)
);

CREATE INDEX IF NOT EXISTS ix_coin_estado ON coincidencias(estado);
CREATE INDEX IF NOT EXISTS ix_coin_score  ON coincidencias(score DESC);

CREATE TABLE IF NOT EXISTS reportes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT REFERENCES videos(video_id),
    tconst      TEXT REFERENCES peliculas(tconst),
    motivo      TEXT NOT NULL,
    detalle     TEXT,
    fecha       TEXT,
    atendido    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cuota (
    fecha_pt    TEXT PRIMARY KEY,
    unidades    INTEGER DEFAULT 0,
    busquedas   INTEGER DEFAULT 0
);
""")
con.commit()
con.close()
print("Tablas recreadas correctamente.")
