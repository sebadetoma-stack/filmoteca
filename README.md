# Filmoteca Clásica

**[→ Ver la filmoteca en línea](https://filmotecaclasica.com)**

Un catálogo de más de 2.500 películas clásicas (1930–1970) disponibles gratuitamente en YouTube, verificadas desde Argentina.

Hecha por [Sebastián De Toma](https://www.linkedin.com/in/juan-sebastian-de-toma/).

---

## ¿Qué es esto?

Hay cientos de películas clásicas completas en YouTube. El problema es que no existe un catálogo confiable: los títulos aparecen en distintos idiomas, se mezclan trailers con películas completas, y muchas desaparecen cuando cambian los derechos.

Esta filmoteca responde una pregunta simple: **¿qué películas clásicas puedo ver hoy, gratis y completas, desde Argentina?**

El catálogo cubre cine estadounidense y británico de 1930 a 1970: film noir, westerns, comedias, dramas, épicas, cine Pre-Code. Cada entrada fue verificada cruzando la duración y el título del video contra los datos de IMDb, descartando trailers, escenas sueltas y copias incompletas.

---

## Cómo funciona

### Arquitectura general

El proyecto tiene dos partes:

1. **Un pipeline local** (Python, SQLite) que construye y mantiene la base de datos
2. **Una web estática** (HTML/JS puro) que lee esa base directamente en el navegador usando [sql.js](https://sql.js.org/)

No hay servidor. No hay backend. El archivo `filmoteca.db` vive en GitHub y el navegador lo carga completo al entrar.

### El pipeline

```
01_ingest_imdb.py   →  Descarga y filtra los datasets de IMDb (1930-1970)
02_cosechar.py      →  Enumera todos los videos de los canales de YouTube
03_matching.py      →  Cruza videos contra el catálogo (offline, cero cuota)
ia_resolver2.py     →  Usa IA para resolver los casos dudosos
04_mantenimiento.py →  Barrido semanal de links caídos
```

### La estrategia de cosecha

En vez de buscar película por película en YouTube (lo que agotaría la cuota de API en días), invertimos la dirección: **cosechamos canales enteros**.

`playlistItems.list` cuesta 1 unidad de cuota por cada 50 videos. Un canal con 800 películas se enumera completo por 16 unidades. Con 10.000 unidades diarias podemos cosechar cientos de canales.

La API de YouTube tiene dos presupuestos independientes:
- **10.000 unidades/día** para playlistItems, videos, channels
- **100 búsquedas/día** para search.list

Las búsquedas quedan reservadas para reparar links caídos.

### El matcher

El cruce de videos contra el catálogo IMDb se hace **completamente offline**, sin cuota. La lógica de decisión tiene tres pasadas:

**Pasada 1 — Vetos duros**

Antes del scoring, se descartan automáticamente los videos que:
- Contienen palabras negativas en el título: trailer, clip, reseña, compilación, maratón, escena, soundtrack, reaction, best of, etc.
- Duran menos de 55 minutos (no son largometrajes)
- Duran más de 1.6× el metraje esperado (recopilaciones o maratones)
- Declaran un año distinto al de la película (±1 año de tolerancia) → probable remake o película diferente

**Pasada 2 — Señal de frase**

La señal más confiable: ¿el título de la película aparece como **frase contigua** en el título del video? Por ejemplo, "1935 - This Woman Is Mine - A savage drama..." contiene la frase "this woman is mine" → match fuerte.

Restricciones importantes:
- Los títulos alternativos (AKAs) en otros idiomas —italiano, francés, alemán, etc.— **no** pueden confirmar por frase. Esto evita que "La Strada" (cuyo AKA en inglés es "The Street") matchee con cualquier video que tenga "street" en el título.
- Para títulos de una sola palabra ("Gilda", "Detour"), se verifica que el video no tenga demasiados tokens clave adicionales —"bridge" en "The Bridge of San Luis Rey" no confirma "The Bridge".
- Frase + duración plausible (72%-130% del metraje) → **confirmado**. El rango amplio cubre versiones TV, cortes europeos y el efecto PAL speedup.

**Pasada 3 — Score ponderado**

Sin frase, el sistema calcula un score combinando similitud de título (50%), duración (33%), año (9%) y confianza del canal (8%). Para confirmar sin frase se exige:
- Similitud de título ≥ 88% + duración exacta (±20%)
- El título que matcheó tiene al menos 2 tokens clave (evita AKAs genéricos de una palabra)

Lo que no alcanza el umbral va a revisión humana o se rechaza.

### Revisión humana

Los casos que el matcher marca como "pendientes" se revisan con una herramienta local (`revision.html`) que muestra cada caso con sus señales: título del video, duración comparada, año. El revisor aprueba, rechaza o marca "es otra película" con atajos de teclado (A/R/S/O). Las decisiones humanas quedan protegidas y nunca se pisan en corridas posteriores del matcher.

### Verificación con IA

Los casos pendientes y los "sin identificar" se pasan a **Claude Haiku** vía la API de Anthropic. El modelo lee el título del video, su descripción completa (que en canales como PizzaFlix incluye director, actores, estudio y año), y la duración, y decide si es match o no.

Se usa en tres escenarios:
- **Pendientes**: videos donde el matcher dudó. La IA los resuelve con ~90% de precisión.
- **Sin identificar**: videos cuyo título en YouTube no corresponde al título del catálogo (ej: "The Fighting Seventh" que es en realidad "Little Big Horn"). La IA extrae título, director y año para buscar el tconst en IMDb.
- **Auditoría periódica**: se corre `ia_auditar.py --score 95` para revisar las confirmadas con score bajo y eliminar falsos positivos que el matcher aceptó con poca certeza. Cuesta centavos para cientos de casos.

### Mejora iterativa

El matcher no se diseñó de una vez — se fue ajustando caso por caso con una suite de tests. Cada fallo real (La Strada → Street Corner, The Bridge → The Bridge of San Luis Rey, Psycho → Psycho Roommate) se convirtió en un test que el sistema tiene que pasar antes de cualquier cambio. El principio es que ningún ajuste puede mejorar un caso sin romper los que ya estaban bien.

### Geobloqueo

`videos.list` devuelve `regionRestriction` con los países bloqueados. Esto filtra lo obvio, pero **no captura** las restricciones de licencia ni Content ID (que es lo que bloquea el Paramount Vault fuera de EE.UU.). Por eso la web muestra solo lo que puede verse desde Argentina según la API, y hay un campo `verificado_ar` con tres estados: `api_ok`, `humano_ok`, `bloqueado`.

---

## Cómo ejecutarlo

### Requisitos

- Python 3.12+
- Sin dependencias externas (solo stdlib)
- Clave de API de YouTube Data API v3 (gratuita, 10.000 unidades/día)
- Clave de API de Anthropic (opcional, para el resolver con IA)

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
export FILMOTECA_PAIS=AR

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

# 6. Aplicar decisiones de la IA
python3 scripts/aplicar_decisiones.py ia_decisiones2.json

# 7. Consultar
python3 scripts/consultar.py --resumen
python3 scripts/consultar.py --genero Film-Noir --decada 1940
python3 scripts/consultar.py --actor "Humphrey Bogart"
python3 scripts/consultar.py --precode
```

### Mantenimiento

```bash
# Semanal: detectar links caídos (400 unidades para 20.000 videos)
python3 scripts/04_mantenimiento.py --barrido

# Reparar lo caído (usa el bucket de 100 búsquedas/día)
python3 scripts/04_mantenimiento.py --reparar
```

---

## Canales cosechados

| Canal | Capa | Notas |
|---|---|---|
| PizzaFlix | Dominio público | Biblioteca privada calidad broadcast. 300+ westerns, 80+ noir |
| Free Vintage Movies | Dominio público | Largometrajes de dominio público |
| Classic Movies 40s 50s 60s | Dominio público | Noir, drama, thriller |
| Classic TV & Movies | Dominio público | Mezcla cine y TV de los 40-60 |
| Golden Age Hollywood | Dominio público | Westerns de serie B |
| Cult Cinema Classics | Particular | Cine europeo y de culto |
| Cult Classic Cinema Archive | Dominio público | Clásicos completos |
| Cine Clásico 10 | Particular | Películas en español |
| La Corriente Películas | Particular | Cine clásico doblado al español latino |
| Mosfilm (English) | Oficial | Canal oficial del estudio soviético, subtítulos en inglés |
| Kino Wizard | Particular | Cine de culto y terror clásico |
| Cine Clásico para Todos | Particular | Cine clásico en español |
| Arte Cine Cultura | Particular | Cine arte y clásico |
| Cinefilia | Dominio público | Películas clásicas completas en español, dominio público |
| Public Domain Movies | Dominio público | Más de 700 títulos, cine mudo y sonoro de dominio público |
| Warner Bros. | Oficial | Algunos títulos completos (verificar disponibilidad AR) |

---

## Pósters y sinopsis

Los pósters y las sinopsis se obtienen de **TMDb** (The Movie Database) vía su API gratuita, cruzando por el `tconst` de IMDb. Las sinopsis se piden primero en español y, si no existen, en inglés.

```bash
export TMDB_API_KEY=tu-clave
python3 scripts/enriquecer_tmdb.py
```

Como el resto de los scripts de enriquecimiento, solo procesa las películas que todavía no tienen póster, así que se puede correr cada vez que se agregan canales nuevos.

## País de producción

El país de producción se obtiene de **Wikidata** vía consultas SPARQL, cruzando el `tconst` de IMDb con la propiedad P495 (país de origen). No requiere API key ni costo. Se corre sobre las películas confirmadas:

```bash
python3 scripts/enriquecer_paises.py
```

El script es reanudable: guarda los países encontrados y en la siguiente corrida solo consulta las que todavía no tienen dato. Permite filtrar en la web por cine estadounidense, británico, italiano, francés, soviético, japonés, etc.

## Funciones adicionales de la web

- **Sorprendeme** (botón ✦): abre una película al azar de las confirmadas visibles en AR
- **Links compartibles**: los filtros activos se reflejan en el hash de la URL (`#genero=Film-Noir&pais=GB`), que podés copiar y compartir
- **Botón ⚑**: aparece en cada tarjeta al pasar el mouse. Abre un formulario de Google para reportar problemas

## Auditoría periódica

Después de agregar canales nuevos o de correr el matcher, conviene auditar las confirmadas con score bajo:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 scripts/ia_auditar.py --score 95        # revisa confirmadas con score < 95
python3 scripts/ia_auditar.py --score 100 --sin-frase  # solo las sin match de frase
```

Los falsos positivos se rechazan directamente en la base. Después copiás el `.db` a `filmoteca-web` y hacés push.

## Agregar películas puntuales

Cuando la IA identifica un video sin match, devuelve título, director y año. Para agregarlas:

```bash
# 1. Buscar el tconst en los datasets de IMDb locales
python3 scripts/buscar_tconst.py para_buscar_en_imdb.json

# 2. Revisar tconst_encontrados.json y agregar al catálogo
python3 scripts/agregar_al_catalogo.py tconst_encontrados.json

# 3. Crear las coincidencias
python3 scripts/agregar_coincidencias.py tconst_encontrados.json
```

## Sistema de reportes

Cada tarjeta tiene un botón **⚑** que aparece al pasar el mouse. Al hacer clic se abre un formulario de Google donde el usuario puede indicar:

- La película no es la que dice ser
- Está incompleta o cortada
- No se puede ver desde Argentina
- Mala calidad (imagen o audio)

El reporte llega por mail al administrador. El video **no se baja automáticamente** — primero se verifica manualmente antes de tomar cualquier decisión. Esto evita que reportes incorrectos o malintencionados eliminen contenido válido.

El flujo técnico de mantenimiento es:
1. El administrador recibe el reporte por mail y en Google Sheets
2. Verifica el video manualmente
3. Si corresponde, corre `python3 rechazar.py` con el video ID para marcarlo como rechazado en la base
4. Sube el `filmoteca.db` actualizado a GitHub

## Licencia

Los datasets de IMDb son para uso **personal y no comercial**.

Los videos pertenecen a sus respectivos canales de YouTube. Este repositorio es solo un catálogo — no aloja ni distribuye ningún contenido.

El código es libre para usar, modificar y distribuir.
