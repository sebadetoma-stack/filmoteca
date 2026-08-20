# Filmoteca Clásica

**[→ Ver la filmoteca en línea](https://filmotecaclasica.com)**

Un catálogo de más de 4.000 películas clásicas (1928–1979) disponibles gratuitamente en YouTube, verificadas desde Argentina.

Hecha por [Sebastián De Toma](https://www.linkedin.com/in/juan-sebastian-de-toma/).

---

## ¿Qué es esto?

Hay cientos de películas clásicas completas en YouTube. El problema es que no existe un catálogo confiable: los títulos aparecen en distintos idiomas, se mezclan trailers con películas completas, y muchas desaparecen cuando cambian los derechos.

Esta filmoteca responde una pregunta simple: **¿qué películas clásicas puedo ver hoy, gratis y completas, desde Argentina?**

El catálogo cubre cine de 1928 a 1979: film noir, westerns, comedias, dramas, épicas, cine Pre-Code, cine de autor europeo y japonés, cine latinoamericano. Cada entrada fue verificada cruzando la duración y el título del video contra los datos de IMDb, descartando trailers, escenas sueltas y copias incompletas.

---

## Cómo funciona

### Arquitectura general

El proyecto tiene dos partes:

1. **Un pipeline local** (Python, SQLite) que construye y mantiene la base de datos
2. **Una web estática** (HTML/JS puro) que lee esa base directamente en el navegador usando [sql.js](https://sql.js.org/)

No hay servidor. No hay backend. La base de datos vive en **Cloudflare R2** y el navegador la carga completa al entrar.

Hay dos archivos de base de datos:
- `filmoteca_completa.db` (~140MB): la DB principal donde escriben todos los scripts locales
- `filmoteca.db` (~17MB): versión liviana con solo las películas confirmadas, generada por `generar_db_web.py` y servida desde R2

### El pipeline

```
01_ingest_imdb.py      →  Descarga y filtra los datasets de IMDb (1928-1979)
02_cosechar.py         →  Enumera todos los videos de los canales de YouTube
03_matching.py         →  Cruza videos contra el catálogo (offline, cero cuota)
ia_resolver2.py        →  Usa IA para resolver los casos dudosos
04_mantenimiento.py    →  Barrido semanal de links caídos
generar_db_web.py      →  Genera la DB liviana para el frontend
generar_paginas.py     →  Genera las páginas individuales por película
```

### La estrategia de cosecha

En vez de buscar película por película en YouTube (lo que agotaría la cuota de API en días), invertimos la dirección: **cosechamos canales enteros**.

`playlistItems.list` cuesta 1 unidad de cuota por cada 50 videos. Un canal con 800 películas se enumera completo por 16 unidades. Con 10.000 unidades diarias podemos cosechar cientos de canales.

La API de YouTube tiene dos presupuestos independientes:
- **10.000 unidades/día** para playlistItems, videos, channels
- **100 búsquedas/día** para search.list

Las búsquedas quedan reservadas para buscar directores o películas específicas.

### El matcher

El cruce de videos contra el catálogo IMDb se hace **completamente offline**, sin cuota. La lógica de decisión tiene tres pasadas:

**Pasada 1 — Vetos duros**

Antes del scoring, se descartan automáticamente los videos que:
- Contienen palabras negativas en el título: trailer, clip, reseña, compilación, maratón, escena, soundtrack, reaction, best of, etc.
- Duran menos de 55 minutos (no son largometrajes)
- Duran más de 1.6× el metraje esperado (recopilaciones o maratones)
- Declaran un año distinto al de la película (±1 año de tolerancia)

**Pasada 2 — Señal de frase**

La señal más confiable: ¿el título de la película aparece como **frase contigua** en el título del video?

Restricciones importantes:
- Los títulos alternativos (AKAs) en otros idiomas no pueden confirmar por frase
- Para títulos de una sola palabra, se verifica que el video no tenga demasiados tokens clave adicionales
- Frase + duración plausible (72%-130% del metraje) → **confirmado**

**Pasada 3 — Score ponderado**

Sin frase, el sistema calcula un score combinando similitud de título (50%), duración (33%), año (9%) y confianza del canal (8%). Para confirmar sin frase se exige similitud ≥ 88% + duración exacta (±20%).

### Verificación con IA

Los casos pendientes y los "sin identificar" se pasan a **Claude Haiku** vía la API de Anthropic. El modelo lee el título del video, su descripción completa, y la duración, y decide si es match o no.

Se usa en tres escenarios:
- **Pendientes**: videos donde el matcher dudó
- **Sin identificar**: videos cuyo título en YouTube no corresponde al título del catálogo
- **Auditoría periódica**: `ia_auditar.py` revisa las confirmadas con score bajo y elimina falsos positivos

### Geobloqueo

`videos.list` devuelve `regionRestriction` con los países bloqueados. Esto filtra lo obvio, pero no captura las restricciones de licencia ni Content ID. Por eso la web muestra solo lo que puede verse desde Argentina según la API.

---

## Cómo ejecutarlo

### Requisitos

- Python 3.12+
- Sin dependencias externas (solo stdlib)
- Clave de API de YouTube Data API v3 (gratuita, 10.000 unidades/día)
- Clave de API de TMDb (gratuita)
- Clave de API de Anthropic (opcional, para resolver con IA)
- Clave de API de OMDB (opcional, gratuita, para posters alternativos)

### Datasets de IMDb

```bash
mkdir -p datos/imdb && cd datos/imdb
for f in title.basics title.akas title.crew title.principals title.ratings name.basics; do
  wget https://datasets.imdbws.com/$f.tsv.gz
done
```

### Pipeline completo

```bash
# Variables de entorno
export YT_API_KEY=tu_clave_youtube
export ANTHROPIC_API_KEY=tu_clave_anthropic   # opcional
export TMDB_API_KEY=tu_clave_tmdb
export OMDB_API_KEY=tu_clave_omdb             # opcional

# 1. Catálogo base desde IMDb (5-10 min, sin red)
python3 scripts/01_ingest_imdb.py --min-votos 30

# 2. Resolver canales de YouTube
python3 scripts/02_cosechar.py --semilla

# 3. Cosechar todos los canales
python3 scripts/02_cosechar.py

# 4. Cruzar videos con el catálogo (sin red, cero cuota)
python3 scripts/03_matching.py

# 5. Resolver pendientes con IA (opcional)
python3 scripts/ia_resolver2.py --pendientes
python3 scripts/aplicar_decisiones.py ia_decisiones2.json

# 6. Enriquecer con posters y sinopsis
python3 scripts/enriquecer_tmdb.py
python3 scripts/enriquecer_paises.py

# 7. Para películas sin poster en TMDb, buscar en OMDB y Wikipedia
python3 scripts/buscar_posters_faltantes.py   # busca en TMDb por título
python3 scripts/buscar_posters_omdb.py        # busca en OMDB (descarta URLs de Amazon)
python3 scripts/buscar_posters_wikipedia.py   # busca imagen en Wikipedia

# 8. Para películas sin sinopsis, buscar en Wikipedia
python3 scripts/buscar_sinopsis_wikipedia.py

# 9. Generar DB liviana y páginas
python3 scripts/generar_db_web.py
python3 scripts/generar_paginas.py
```

### Mantenimiento

```bash
# Semanal: detectar links caídos
python3 scripts/04_mantenimiento.py --barrido

# Reparar lo caído
python3 scripts/04_mantenimiento.py --reparar

# Auditar confirmadas con score bajo
python3 scripts/ia_auditar.py --score 95

# Ver estado de posters y sinopsis
python3 scripts/ver_sin_poster_total.py
python3 scripts/ver_faltantes_detalle.py

# Ver estado de un canal
python3 scripts/ver_canal.py CHANNEL_ID
```

### Flujo de publicación

```bash
# 1. Borrar output_paginas/pelicula/
# 2. Generar DB liviana y páginas
python3 scripts/generar_db_web.py
python3 scripts/generar_paginas.py

# 3. Copiar output_paginas/pelicula/ a filmoteca-web/pelicula/
# 4. Copiar sitemap.xml a filmoteca-web/
# 5. Subir filmoteca.db y filmoteca_completa.db a Cloudflare R2 (bucket filmoteca-db)
# 6. Push a GitHub
git add pelicula/ sitemap.xml scripts/ datos/canales_semilla.csv
git commit -m "descripción de los cambios"
git push
```

---

## Canales cosechados

| Canal | Notas |
|---|---|
| La Corriente Películas | Cine clásico doblado al español latino |
| Mosfilm (English) | Canal oficial del estudio soviético, subtítulos en inglés |
| Kino Wizard | Cine de culto y terror clásico |
| Cine Clásico para Todos | Cine clásico en español |
| Arte Cine Cultura | Cine clásico europeo y latinoamericano |
| Film&Clips | Largometrajes clásicos completos (3 sub-canales) |
| NipponKino | Cine japonés clásico con subtítulos en inglés |
| MeduFiles | Películas europeas de autor |
| prisoner | Películas de autor europeas |
| Khris McLorean | Cine europeo clásico |
| Artflix Películas Clásicas | Cine clásico variado |
| Grandpa's Old Movies Chest | Dominio público americano |
| Davide Fiammenghi | Bergman y europeos con subtítulos en inglés |
| Ruvindu Gamage | Mezcla de cine europeo y japonés clásico |
| MrCinefilia | Cine clásico variado |
| Ódor Endre | Cine clásico europeo |
| Cinema__Routine | Cine de autor variado |
| CRFA \| Época de Oro | Cine argentino de la época de oro |
| Lo que el cine nos dejó | Cine argentino clásico |
| Y otros canales de dominio público | PizzaFlix, Free Vintage Movies, DK Classics, etc. |

---

## Pósters y sinopsis

Los pósters y sinopsis se obtienen de múltiples fuentes en orden de prioridad:

1. **TMDb** (The Movie Database): fuente principal, via tconst de IMDb y búsqueda por título
2. **OMDB** (Open Movie Database): para películas no encontradas en TMDb. Se descartan URLs de Amazon por restricciones de hotlinking
3. **Wikipedia**: imagen principal del artículo, para películas muy oscuras no indexadas en TMDb ni OMDB
4. **Wikipedia** (sinopsis): extracto del artículo en español, o en inglés traducido con Claude

---

## Funciones adicionales de la web

- **Sorprendeme** (botón ✦): abre una película al azar
- **Links compartibles**: los filtros activos se reflejan en el hash de la URL
- **Páginas individuales**: cada película tiene su propia URL estática con schema.org, meta tags, datos técnicos y películas relacionadas
- **Login con Google**: podés guardar favoritos, marcar películas como vistas y llevar un historial (Firebase Firestore)
- **Botón ⚑**: reportar problemas — video caído, no disponible en AR, mala calidad

---

## Sistema de reportes

El flujo técnico de mantenimiento ante un reporte:
1. El administrador recibe el reporte en Google Sheets
2. Verifica el video manualmente
3. Si hay versión alternativa confirmada en la DB, se actualiza el `video_id`. Si no, se busca reemplazo en YouTube
4. Se corre `generar_db_web.py`, se sube a R2 y se hace push

---

## Licencia

Los datasets de IMDb son para uso **personal y no comercial**.

Los videos pertenecen a sus respectivos canales de YouTube. Este repositorio es solo un catálogo — no aloja ni distribuye ningún contenido.

El código es libre para usar, modificar y distribuir.
