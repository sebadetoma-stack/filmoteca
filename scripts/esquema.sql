-- Filmoteca clásica en YouTube (1930-1970)
-- Esquema SQLite. Todo lo que viene de IMDb queda marcado como tal,
-- para poder re-derivarlo desde TMDb/Wikidata si el proyecto se hace público.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------
-- CATÁLOGO (origen: IMDb non-commercial datasets)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS peliculas (
    tconst          TEXT PRIMARY KEY,        -- tt0033467
    titulo_orig     TEXT NOT NULL,           -- originalTitle
    titulo_primario TEXT NOT NULL,           -- primaryTitle (el "más conocido" según IMDb)
    anio            INTEGER NOT NULL,
    duracion_min    INTEGER,                 -- runtimeMinutes; puede ser NULL
    generos         TEXT,                    -- CSV tal cual viene de IMDb
    rating          REAL,
    votos           INTEGER,
    -- derivados
    decada          INTEGER,                 -- 1930, 1940, ...
    es_precode      INTEGER DEFAULT 0,       -- 0=no, 1=sí, 2=zona gris (1934)
    pd_probable     INTEGER DEFAULT 0,       -- dominio público probable (heurística)
    fuente          TEXT DEFAULT 'imdb'
);

CREATE INDEX IF NOT EXISTS ix_pel_anio    ON peliculas(anio);
CREATE INDEX IF NOT EXISTS ix_pel_decada  ON peliculas(decada);
CREATE INDEX IF NOT EXISTS ix_pel_votos   ON peliculas(votos DESC);

-- Títulos alternativos: la clave para el matching y para las búsquedas en español.
CREATE TABLE IF NOT EXISTS titulos_alt (
    tconst   TEXT NOT NULL REFERENCES peliculas(tconst) ON DELETE CASCADE,
    titulo   TEXT NOT NULL,
    region   TEXT,                           -- AR, ES, MX, US, ...
    idioma   TEXT,
    norm     TEXT NOT NULL                   -- título normalizado, para el join rápido
);
CREATE INDEX IF NOT EXISTS ix_alt_tconst ON titulos_alt(tconst);
CREATE INDEX IF NOT EXISTS ix_alt_norm   ON titulos_alt(norm);

CREATE TABLE IF NOT EXISTS personas (
    nconst  TEXT PRIMARY KEY,
    nombre  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creditos (
    tconst  TEXT NOT NULL REFERENCES peliculas(tconst) ON DELETE CASCADE,
    nconst  TEXT NOT NULL REFERENCES personas(nconst),
    rol     TEXT NOT NULL,                   -- director | actor
    orden   INTEGER,
    PRIMARY KEY (tconst, nconst, rol)
);
CREATE INDEX IF NOT EXISTS ix_cred_nconst ON creditos(nconst, rol);

-- ---------------------------------------------------------------
-- YOUTUBE
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canales (
    channel_id      TEXT PRIMARY KEY,        -- UCxxxxxxxx
    uploads_id      TEXT,                    -- UUxxxxxxxx (playlist de subidas)
    handle          TEXT,
    nombre          TEXT,
    capa            TEXT NOT NULL,           -- dominio_publico | oficial | particular
    confianza       INTEGER DEFAULT 50,      -- 0-100, pondera el score de matching
    ultima_cosecha  TEXT,
    total_videos    INTEGER,
    notas           TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id        TEXT PRIMARY KEY,        -- 11 chars
    channel_id      TEXT REFERENCES canales(channel_id),
    titulo          TEXT NOT NULL,
    descripcion     TEXT,
    duracion_seg    INTEGER,
    publicado       TEXT,
    idioma_audio    TEXT,                    -- defaultAudioLanguage
    subtitulos      INTEGER DEFAULT 0,       -- contentDetails.caption
    definicion      TEXT,                    -- hd | sd
    -- geobloqueo: lo que la API declara
    region_allowed  TEXT,                    -- CSV o NULL
    region_blocked  TEXT,                    -- CSV o NULL
    ve_ar           INTEGER,                 -- 1=sí según API, 0=no, NULL=desconocido
    -- estado de vida
    activo          INTEGER DEFAULT 1,
    visto_ultima_vez TEXT,
    caido_desde     TEXT
);
CREATE INDEX IF NOT EXISTS ix_vid_canal  ON videos(channel_id);
CREATE INDEX IF NOT EXISTS ix_vid_activo ON videos(activo);
CREATE INDEX IF NOT EXISTS ix_vid_dur    ON videos(duracion_seg);

-- ---------------------------------------------------------------
-- EL CRUCE: qué video corresponde a qué película
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coincidencias (
    tconst      TEXT NOT NULL REFERENCES peliculas(tconst) ON DELETE CASCADE,
    video_id    TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    score       REAL NOT NULL,               -- 0-100
    senales     TEXT,                        -- JSON con el desglose del score
    estado      TEXT NOT NULL DEFAULT 'pendiente',
        -- confirmada | pendiente | rechazada
    verificado_ar TEXT DEFAULT 'sin_datos',
        -- api_ok | humano_ok | bloqueado | sin_datos
    revisado_por TEXT,                       -- 'auto' | 'humano'
    notas       TEXT,
    creado      TEXT,
    PRIMARY KEY (tconst, video_id)
);
CREATE INDEX IF NOT EXISTS ix_coin_estado ON coincidencias(estado);
CREATE INDEX IF NOT EXISTS ix_coin_score  ON coincidencias(score DESC);

-- Reportes de usuarios: el canal humano para lo que la API no ve.
CREATE TABLE IF NOT EXISTS reportes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT REFERENCES videos(video_id),
    tconst      TEXT REFERENCES peliculas(tconst),
    motivo      TEXT NOT NULL,
        -- no_reproduce | geobloqueado | incompleta | mala_calidad |
        -- pelicula_equivocada | sin_audio | otro
    detalle     TEXT,
    fecha       TEXT,
    atendido    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_rep_atendido ON reportes(atendido);

-- Contabilidad de cuota: dos buckets independientes.
CREATE TABLE IF NOT EXISTS cuota (
    fecha_pt    TEXT PRIMARY KEY,            -- día en Pacific Time
    unidades    INTEGER DEFAULT 0,           -- pool de 10.000
    busquedas   INTEGER DEFAULT 0            -- bucket de 100
);

-- ---------------------------------------------------------------
-- VISTA PRINCIPAL: lo que realmente se consulta
-- ---------------------------------------------------------------
CREATE VIEW IF NOT EXISTS filmoteca AS
SELECT
    p.tconst,
    p.titulo_primario           AS titulo,
    p.titulo_orig,
    p.anio,
    p.decada,
    p.generos,
    p.duracion_min,
    p.rating,
    p.votos,
    p.es_precode,
    (SELECT GROUP_CONCAT(pe.nombre, ', ')
       FROM creditos c JOIN personas pe ON pe.nconst = c.nconst
      WHERE c.tconst = p.tconst AND c.rol = 'director')      AS directores,
    (SELECT GROUP_CONCAT(pe.nombre, ', ')
       FROM (SELECT c.tconst, c.nconst FROM creditos c
              WHERE c.rol = 'actor' ORDER BY c.orden LIMIT 4) c
       JOIN personas pe ON pe.nconst = c.nconst
      WHERE c.tconst = p.tconst)                             AS reparto,
    v.video_id,
    'https://youtu.be/' || v.video_id                        AS url,
    v.duracion_seg / 60                                      AS yt_min,
    v.idioma_audio,
    v.subtitulos,
    v.definicion,
    v.ve_ar,
    ca.nombre                                                AS canal,
    ca.capa,
    co.score,
    co.estado,
    co.verificado_ar
FROM peliculas p
JOIN coincidencias co ON co.tconst = p.tconst
JOIN videos v         ON v.video_id = co.video_id
LEFT JOIN canales ca  ON ca.channel_id = v.channel_id
WHERE v.activo = 1 AND co.estado != 'rechazada';
