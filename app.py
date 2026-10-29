"""
API de radio y búsqueda de YouTube.
Sin yt-dlp y sin API key oficial de YouTube.

Endpoints:
  GET /                         -> documentación
  GET /radio?id=<id|link>&n=25[&fuente=youtubei|ytmusic]
  GET /buscar?q=<texto>&n=10
  GET /id?url=<link>
  GET /salud

La radio devuelve:
  id, titulo, artista, duracion, duracion_segundos,
  album, miniatura y url.

Filtro musical:
  - Duración mínima: 60 segundos.
  - Duración máxima: 420 segundos (7 minutos).
  - Excluye mixes, megamixes, mashups, álbumes completos,
    playlists, tutoriales, reacciones y otros videos no musicales.
  - Elimina IDs duplicados.
  - Busca candidatos adicionales para intentar completar
    la cantidad solicitada.

API_KEY es opcional para proteger TU API.
No es una clave de YouTube.
"""

import hmac
import json
import os
import re
import unicodedata
import urllib.request

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException


app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False


ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{11}$")

URL_ID_REGEX = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)"
    r"([A-Za-z0-9_-]{11})"
)


# ==========================================================
# CONFIGURACIÓN DEL FILTRO MUSICAL
# ==========================================================

DURACION_MINIMA = 60
DURACION_MAXIMA = 7 * 60

# Se buscan más candidatos que los solicitados porque
# algunos se descartarán al aplicar el filtro.
FACTOR_CANDIDATOS = 4
MAX_CANDIDATOS = 100


# Frases que indican que probablemente no sea una canción normal.
FRASES_EXCLUIDAS = (
    "full album",
    "complete album",
    "album completo",
    "album completo canciones",
    "full playlist",
    "playlist completa",
    "official playlist",
    "full mix",
    "mega mix",
    "megamix",
    "megamix completo",
    "megamix cumbia",
    "megamix reggaeton",
    "megamix bachata",
    "megamix salsa",
    "megamix merengue",
    "continuous mix",
    "dj mix",
    "mix completo",
    "mix de canciones",
    "mix de exitos",
    "mix de éxitos",
    "mashup",
    "tutorial",
    "tutorial de guitarra",
    "tutorial de piano",
    "como tocar",
    "como cantar",
    "how to play",
    "how to sing",
    "reaction",
    "reaccion",
    "reacción",
    "review",
    "entrevista",
    "interview",
    "podcast",
    "noticias",
    "news",
    "analisis",
    "análisis",
    "gameplay",
    "detras de camaras",
    "detrás de cámaras",
    "making of",
    "karaoke instrumental",
    "instrumental karaoke",
    "letra y traduccion",
    "letra y traducción",
)

# Indicadores que normalmente describen recopilaciones,
# aunque el título no contenga la palabra "mix".
INDICADORES_RECORRIDO = (
    " nonstop ",
    " non stop ",
    " sin parar ",
    " una hora ",
    " 1 hora ",
    " 2 horas ",
    " 3 horas ",
    " 10 canciones ",
    " 20 canciones ",
    " 50 canciones ",
    " los mejores exitos ",
    " los mejores éxitos ",
    " mejores canciones de ",
    " recopilacion ",
    " recopilación ",
    " compilacion ",
    " compilación ",
    " playlist ",
)


# ==========================================================
# UTILIDADES
# ==========================================================

def parse_video_id(texto):
    """Acepta un ID de YouTube o un enlace compatible."""
    texto = (texto or "").strip()

    if ID_REGEX.fullmatch(texto):
        return texto

    match = URL_ID_REGEX.search(texto)
    return match.group(1) if match else None


def unicos(ids, n):
    """Elimina IDs inválidos y duplicados, conservando el orden."""
    vistos = set()
    salida = []

    for video_id in ids:
        if (
            isinstance(video_id, str)
            and ID_REGEX.fullmatch(video_id)
            and video_id not in vistos
        ):
            vistos.add(video_id)
            salida.append(video_id)

            if len(salida) >= n:
                break

    return salida


def entero(nombre, defecto, minimo, maximo):
    try:
        valor = int(request.args.get(nombre, defecto))
        return max(minimo, min(valor, maximo))
    except (ValueError, TypeError):
        return defecto


def error(status, codigo, mensaje, detalle=None):
    respuesta = jsonify({
        "ok": False,
        "error": {
            "codigo": codigo,
            "mensaje": mensaje,
            "detalle": detalle,
        },
    })
    respuesta.status_code = status
    return respuesta


def texto_simple(objeto):
    """Extrae texto de estructuras de texto habituales de YouTube."""
    if not isinstance(objeto, dict):
        return ""

    if isinstance(objeto.get("simpleText"), str):
        return objeto["simpleText"]

    runs = objeto.get("runs")

    if isinstance(runs, list):
        return "".join(
            str(run.get("text", ""))
            for run in runs
            if isinstance(run, dict)
        )

    return ""


def extraer_texto_renderer(renderer, *nombres):
    """Busca texto en los campos indicados de un renderer."""
    for nombre in nombres:
        valor = texto_simple(renderer.get(nombre))

        if valor:
            return valor.strip()

    return ""


def extraer_album(renderer):
    """Intenta obtener el álbum cuando la respuesta lo incluye."""
    for nombre in ("longBylineText", "shortBylineText"):
        byline = renderer.get(nombre)

        if not isinstance(byline, dict):
            continue

        runs = byline.get("runs", [])

        for run in runs:
            if not isinstance(run, dict):
                continue

            texto = (run.get("text") or "").strip()
            endpoint = run.get("navigationEndpoint", {})
            browse_endpoint = endpoint.get("browseEndpoint", {})

            page_type = (
                browse_endpoint
                .get("browseEndpointContextSupportedConfigs", {})
                .get("browseEndpointContextMusicConfig", {})
                .get("pageType", "")
            )

            if "ALBUM" in str(page_type).upper():
                return texto

    return ""


def extraer_miniatura(renderer, video_id):
    """Obtiene la miniatura del JSON o usa una URL estándar."""
    thumbnails = (
        renderer.get("thumbnail", {})
        .get("thumbnails", [])
    )

    if isinstance(thumbnails, list) and thumbnails:
        validas = [
            t for t in thumbnails
            if isinstance(t, dict) and t.get("url")
        ]

        if validas:
            return validas[-1]["url"]

    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def duracion_a_segundos(duracion):
    """Convierte mm:ss o hh:mm:ss a segundos."""
    if not duracion:
        return 0

    try:
        partes = [int(p) for p in str(duracion).strip().split(":")]

        if not 1 <= len(partes) <= 3:
            return 0

        total = 0

        for parte in partes:
            if parte < 0:
                return 0

            total = total * 60 + parte

        return total

    except (ValueError, TypeError):
        return 0


def normalizar_texto(texto):
    """Minúsculas, sin tildes y con espacios normalizados."""
    texto = unicodedata.normalize("NFD", str(texto or "").lower())
    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return f" {texto.strip()} "


def es_cancion_valida(pista):
    """
    Devuelve True si el resultado parece una canción normal
    y su duración está entre 1 y 7 minutos.

    Los videos sin duración conocida se descartan por seguridad.
    """
    if not isinstance(pista, dict):
        return False

    titulo = str(pista.get("titulo") or "").strip()

    if not titulo or titulo.lower() == "canción desconocida":
        return False

    duracion = pista.get("duracion_segundos")

    try:
        duracion = int(duracion or 0)
    except (ValueError, TypeError):
        duracion = 0

    if not DURACION_MINIMA <= duracion <= DURACION_MAXIMA:
        return False

    titulo_normalizado = normalizar_texto(titulo)

    for frase in FRASES_EXCLUIDAS:
        if normalizar_texto(frase).strip() in titulo_normalizado:
            return False

    for indicador in INDICADORES_RECORRIDO:
        if indicador in titulo_normalizado:
            return False

    return True


def filtrar_canciones(canciones, n):
    """
    Filtra canciones largas o poco relevantes y elimina duplicados.
    Conserva el orden original y devuelve como máximo n canciones.
    """
    salida = []
    vistos = set()

    for pista in canciones:
        if not isinstance(pista, dict):
            continue

        video_id = pista.get("id")

        if not isinstance(video_id, str):
            continue

        if not ID_REGEX.fullmatch(video_id):
            continue

        if video_id in vistos:
            continue

        if not es_cancion_valida(pista):
            continue

        vistos.add(video_id)
        salida.append(pista)

        if len(salida) >= n:
            break

    return salida


def normalizar_pista_ytmusic(track):
    """Normaliza una pista recibida de ytmusicapi."""
    video_id = track.get("videoId")

    if not isinstance(video_id, str) or not ID_REGEX.fullmatch(video_id):
        return None

    artistas = track.get("artists") or []

    nombres = [
        str(a["name"])
        for a in artistas
        if isinstance(a, dict) and a.get("name")
    ]

    album = track.get("album")

    album_nombre = (
        str(album.get("name") or "")
        if isinstance(album, dict)
        else ""
    )

    duracion = str(track.get("duration") or "")

    thumbnails = track.get("thumbnails") or []
    miniatura = ""

    if thumbnails:
        ultima = thumbnails[-1]

        if isinstance(ultima, dict):
            miniatura = ultima.get("url", "")

    if not miniatura:
        miniatura = (
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        )

    return {
        "id": video_id,
        "titulo": str(track.get("title") or "Canción desconocida"),
        "artista": ", ".join(nombres) or "Artista desconocido",
        "duracion": duracion,
        "duracion_segundos": duracion_a_segundos(duracion),
        "album": album_nombre,
        "miniatura": miniatura,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


# ==========================================================
# SEGURIDAD DE TU API
# ==========================================================

@app.before_request
def verificar_clave():
    # API_KEY protege tu servidor, no es una clave de YouTube.
    clave = os.environ.get("API_KEY")

    if (
        not clave
        or request.method == "OPTIONS"
        or request.path in ("/", "/salud")
    ):
        return None

    enviada = (
        request.headers.get("X-API-Key")
        or request.args.get("key")
        or ""
    )

    if not hmac.compare_digest(enviada, clave):
        return error(
            401,
            "NO_AUTORIZADO",
            "Falta o es incorrecta la clave de esta API.",
        )

    return None


@app.after_request
def cabeceras(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = (
        "X-API-Key, Content-Type"
    )
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return resp


@app.errorhandler(HTTPException)
def http_error(e):
    return error(
        e.code or 500,
        e.name.upper().replace(" ", "_"),
        e.description,
    )


@app.errorhandler(Exception)
def error_inesperado(e):
    app.logger.exception("Error inesperado")

    return error(
        500,
        "ERROR_INESPERADO",
        "Error inesperado.",
        f"{type(e).__name__}: {e}",
    )


# ==========================================================
# RADIO MEDIANTE YOUTUBEI
# ==========================================================

def radio_youtubei(video_id, n):
    """
    Extrae candidatos de playlistPanelVideoRenderer.
    El filtrado musical definitivo se aplica en el endpoint /radio.
    """
    cuerpo = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20250101.00.00",
                "hl": "es",
                "gl": "US",
            }
        },
        "videoId": video_id,
        "playlistId": f"RD{video_id}",
    }

    req = urllib.request.Request(
        "https://www.youtube.com/youtubei/v1/next?prettyPrint=false",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Origin": "https://www.youtube.com",
            "Accept-Language": "es-ES,es;q=0.9",
        },
        method="POST",
    )

    proxy = os.environ.get("YT_PROXY")

    manejador = (
        urllib.request.ProxyHandler({
            "http": proxy,
            "https": proxy,
        })
        if proxy
        else urllib.request.ProxyHandler()
    )

    opener = urllib.request.build_opener(manejador)

    with opener.open(req, timeout=15) as respuesta:
        data = json.load(respuesta)

    pistas = []

    def recorrer(objeto):
        if isinstance(objeto, dict):
            renderer = objeto.get("playlistPanelVideoRenderer")

            if isinstance(renderer, dict):
                track_id = renderer.get("videoId")

                if (
                    isinstance(track_id, str)
                    and ID_REGEX.fullmatch(track_id)
                ):
                    titulo = extraer_texto_renderer(
                        renderer, "title"
                    )

                    artista = extraer_texto_renderer(
                        renderer,
                        "shortBylineText",
                        "longBylineText",
                    )

                    duracion = extraer_texto_renderer(
                        renderer, "lengthText"
                    )

                    pistas.append({
                        "id": track_id,
                        "titulo": titulo or "Canción desconocida",
                        "artista": artista or "Artista desconocido",
                        "duracion": duracion,
                        "duracion_segundos": duracion_a_segundos(
                            duracion
                        ),
                        "album": extraer_album(renderer),
                        "miniatura": extraer_miniatura(
                            renderer, track_id
                        ),
                        "url": (
                            f"https://www.youtube.com/watch?v={track_id}"
                        ),
                    })

            for valor in objeto.values():
                recorrer(valor)

        elif isinstance(objeto, list):
            for valor in objeto:
                recorrer(valor)

    recorrer(data)

    # Devuelve candidatos sin aplicar todavía el límite final.
    # Así el endpoint puede filtrar antes de escoger las n canciones.
    salida = []
    vistos = set()

    for pista in pistas:
        if pista["id"] in vistos:
            continue

        vistos.add(pista["id"])
        salida.append(pista)

        if len(salida) >= n:
            break

    return salida


# ==========================================================
# RADIO MEDIANTE YOUTUBE MUSIC
# ==========================================================

def radio_ytmusic(video_id, n):
    """Obtiene candidatos con ytmusicapi, sin clave oficial."""
    from ytmusicapi import YTMusic

    ytmusic = YTMusic()

    data = ytmusic.get_watch_playlist(
        videoId=video_id,
        radio=True,
        limit=n,
    )

    resultados = []
    vistos = set()

    for track in data.get("tracks", []):
        pista = normalizar_pista_ytmusic(track)

        if not pista or pista["id"] in vistos:
            continue

        vistos.add(pista["id"])
        resultados.append(pista)

        if len(resultados) >= n:
            break

    return resultados


FUENTES = {
    "youtubei": radio_youtubei,
    "ytmusic": radio_ytmusic,
}


# ==========================================================
# ENDPOINTS
# ==========================================================

@app.get("/")
def inicio():
    return jsonify({
        "nombre": "API de radio de YouTube",
        "endpoints": {
            "/radio": (
                "?id=<id|link>&n=25&fuente=youtubei|ytmusic "
                "-> canciones filtradas de 1 a 7 minutos"
            ),
            "/buscar": (
                "?q=<texto>&n=10 -> búsqueda de videos filtrados"
            ),
            "/id": "?url=<link> -> extrae el ID",
            "/salud": "estado del servicio",
        },
        "filtro_musical": {
            "duracion_minima_segundos": DURACION_MINIMA,
            "duracion_maxima_segundos": DURACION_MAXIMA,
            "excluye": [
                "mixes y megamixes",
                "álbumes completos y playlists",
                "tutoriales y reacciones",
                "videos sin duración conocida",
            ],
        },
        "autenticacion": (
            "API_KEY propia"
            if os.environ.get("API_KEY")
            else "ninguna"
        ),
    })


@app.get("/salud")
def salud():
    return jsonify({"ok": True})


@app.get("/id")
def sacar_id():
    video_id = parse_video_id(
        request.args.get("url")
        or request.args.get("id")
        or ""
    )

    if not video_id:
        return error(
            400,
            "ENTRADA_INVALIDA",
            "No se encontró un ID de video válido.",
        )

    return jsonify({"ok": True, "id": video_id})


@app.get("/radio")
def radio():
    video_id = parse_video_id(
        request.args.get("id")
        or request.args.get("url")
        or ""
    )

    if not video_id:
        return error(
            400,
            "ENTRADA_INVALIDA",
            "Envía un ID de 11 caracteres o un enlace válido.",
        )

    n = entero("n", 25, 1, 50)

    elegida = (
        request.args.get("fuente") or ""
    ).strip().lower()

    if elegida and elegida not in FUENTES:
        return error(
            400,
            "FUENTE_INVALIDA",
            f"Fuente desconocida. Usa: {', '.join(FUENTES)}.",
        )

    orden = (
        [(elegida, FUENTES[elegida])]
        if elegida
        else list(FUENTES.items())
    )

    errores = {}

    # Pedimos más candidatos de los que el usuario necesita.
    candidatos_n = min(
        max(n * FACTOR_CANDIDATOS, n),
        MAX_CANDIDATOS,
    )

    for nombre, funcion in orden:
        try:
            candidatos = funcion(video_id, candidatos_n)

            # FILTRO MUSICAL INTEGRADO
            canciones = filtrar_canciones(candidatos, n)

            if not canciones:
                errores[nombre] = (
                    "No se encontraron canciones que cumplan "
                    "el filtro de 1 a 7 minutos."
                )
                continue

            respuesta = jsonify({
                "ok": True,
                "semilla": video_id,
                "fuente": nombre,
                "total": len(canciones),
                "ids": [c["id"] for c in canciones],
                "resultados": canciones,
            })

            respuesta.headers["Cache-Control"] = "no-store"
            return respuesta

        except Exception as e:
            app.logger.warning(
                "radio %s falló: %s",
                nombre,
                e,
            )

            errores[nombre] = (
                f"{type(e).__name__}: {str(e)[:300]}"
            )

    return error(
        502,
        "RADIO_NO_DISPONIBLE",
        "No se pudo obtener canciones válidas para la radio.",
        errores,
    )


@app.get("/buscar")
def buscar():
    q = (request.args.get("q") or "").strip()

    if not q:
        return error(
            400,
            "FALTA_BUSQUEDA",
            "Falta el parámetro 'q' con el texto a buscar.",
        )

    n = entero("n", 10, 1, 25)

    try:
        from ytmusicapi import YTMusic

        ytmusic = YTMusic()

        encontrados = ytmusic.search(
            q,
            filter="songs",
            limit=min(n * FACTOR_CANDIDATOS, MAX_CANDIDATOS),
        )

    except Exception as e:
        return error(
            502,
            "BUSQUEDA_FALLIDA",
            "No se pudo realizar la búsqueda.",
            f"{type(e).__name__}: {str(e)[:300]}",
        )

    candidatos = []
    vistos = set()

    for encontrado in encontrados:
        pista = normalizar_pista_ytmusic(encontrado)

        if not pista or pista["id"] in vistos:
            continue

        vistos.add(pista["id"])
        candidatos.append(pista)

    # Se aplica el mismo filtro también a la búsqueda.
    resultados = filtrar_canciones(candidatos, n)

    respuesta = jsonify({
        "ok": True,
        "consulta": q,
        "total": len(resultados),
        "resultados": resultados,
    })

    respuesta.headers["Cache-Control"] = (
        "s-maxage=300, stale-while-revalidate"
    )

    return respuesta


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
    )
