# Filmoteca Clásica

**[→ Ver la filmoteca en línea](https://sebadetoma-stack.github.io/filmoteca)**

Un catálogo de más de 2.300 películas clásicas (1930–1970) disponibles gratuitamente en YouTube, verificadas desde Argentina.

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

El cruce de videos contra el catálogo IMDb se hace **completamente offline**, sin cuota, usando tres señales:

1. **Frase**: ¿el título de la película aparece textualmente en el título del video?
2. **Duración**: ¿el video dura lo que dura la película (±20%)?
3. **Año**: ¿el año declarado en el título del video coincide con el de IMDb?

Los videos con palabras negativas (trailer, clip, reseña, compilación, maratón) son vetados antes del scoring. Los que duran más de 1.6× el metraje esperado también.

La lógica de decisión tiene tres pasadas:
- **Vetos duros** → rechazado, sin importar el score
- **Frase + duración plausible** → confirmado directamente
- **Score alto + duración exacta** → confirmado con criterio de tokens mínimos

### Verificación con IA

Los casos que el matcher no puede resolver solo (duraciones que difieren, títulos ambiguos) se pasan a Claude Haiku vía la API de Anthropic. El modelo lee el título del video, la descripción del canal, la duración, y decide si es match o no. Cuesta centavos para cientos de casos.

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
| Warner Bros. | Oficial | Algunos títulos completos (verificar disponibilidad AR) |

---

## Licencia

Los datasets de IMDb son para uso **personal y no comercial**.

Los videos pertenecen a sus respectivos canales de YouTube. Este repositorio es solo un catálogo — no aloja ni distribuye ningún contenido.

El código es libre para usar, modificar y distribuir.
