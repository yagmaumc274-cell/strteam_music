"""API de consulta: IDs de la radio de un video de YouTube (y búsqueda de IDs). Sin yt-dlp..

Endpoints (todos devuelven JSON):
  GET /                       -> documentación breve
  GET /radio?id=<id|link>&n=25[&fuente=youtubei|ytmusic]
  GET /buscar?q=<texto>&n=10
  GET /id?url=<link>
  GET /salud

Seguridad opcional: si defines la variable de entorno API_KEY, hay que enviar
la clave en el encabezado  X-API-Key: <clave>  (o en ?key=<clave>).
Proxy opcional: variable YT_PROXY (http://usuario:clave@host:puerto), solo para la fuente youtubei.
"""
import hmac
import json
import os
import re
import urllib.request

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False

ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_ID_REGEX = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


# ---------- utilidades ----------
def parse_video_id(texto):
    """Acepta un ID de 11 caracteres o un link de YouTube (watch, youtu.be, shorts, embed)."""
    texto = (texto or "").strip()
    if ID_REGEX.match(texto):
        return texto
    m = URL_ID_REGEX.search(texto)
    return m.group(1) if m else None


def unicos(ids, n):
    """Quita vacíos, inválidos y repetidos conservando el orden."""
    vistos, salida = set(), []
    for i in ids:
        if i and ID_REGEX.match(i) and i not in vistos:
            vistos.add(i)
            salida.append(i)
    return salida[:n]


def entero(nombre, defecto, minimo, maximo):
    try:
        return max(minimo, min(int(request.args.get(nombre, defecto)), maximo))
    except ValueError:
        return defecto


def error(status, codigo, mensaje, detalle=None):
    r = jsonify({"ok": False, "error": {"codigo": codigo, "mensaje": mensaje, "detalle": detalle}})
    r.status_code = status
    return r



# ---------- seguridad y respuestas ----------
@app.before_request
def verificar_clave():
    clave = os.environ.get("API_KEY")
    if not clave or request.method == "OPTIONS" or request.path in ("/", "/salud"):
        return None
    enviada = request.headers.get("X-API-Key") or request.args.get("key") or ""
    if not hmac.compare_digest(enviada, clave):
        return error(401, "NO_AUTORIZADO", "Falta o es incorrecta la clave de la API (X-API-Key).")
    return None


@app.after_request
def cabeceras(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "X-API-Key, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return resp


@app.errorhandler(HTTPException)
def http_error(e):
    return error(e.code or 500, e.name.upper().replace(" ", "_"), e.description)


@app.errorhandler(Exception)
def error_inesperado(e):
    app.logger.exception("Error inesperado")
    return error(500, "ERROR_INESPERADO", "Error inesperado.", f"{type(e).__name__}: {e}")


# ---------- fuentes de radio ----------
def radio_youtubei(video_id, n):
    """Pide el Mix (RD<id>) directamente a YouTube, sin librerías."""
    cuerpo = {
        "context": {"client": {"clientName": "WEB", "clientVersion": "2.20250101.00.00",
                               "hl": "es", "gl": "US"}},
        "videoId": video_id,
        "playlistId": f"RD{video_id}",
    }
    req = urllib.request.Request(
        "https://www.youtube.com/youtubei/v1/next?prettyPrint=false",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Origin": "https://www.youtube.com",
            "Accept-Language": "es-ES,es;q=0.9",
        },
        method="POST",
    )
    proxy = os.environ.get("YT_PROXY")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy
        else urllib.request.ProxyHandler())
    with opener.open(req, timeout=10) as r:
        data = json.load(r)

    ids = []

    def recorrer(x):
        if isinstance(x, dict):
            pv = x.get("playlistPanelVideoRenderer")
            if isinstance(pv, dict) and pv.get("videoId"):
                ids.append(pv["videoId"])
            for v in x.values():
                recorrer(v)
        elif isinstance(x, list):
            for v in x:
                recorrer(v)

    recorrer(data)
    return unicos(ids, n)


def radio_ytmusic(video_id, n):
    from ytmusicapi import YTMusic
    data = YTMusic().get_watch_playlist(videoId=video_id, radio=True, limit=n)
    return unicos([t.get("videoId") for t in data.get("tracks", [])], n)


FUENTES = {"youtubei": radio_youtubei, "ytmusic": radio_ytmusic}


# ---------- endpoints ----------
@app.get("/")
def inicio():
    return jsonify({
        "nombre": "API de radio de YouTube (solo IDs)",
        "endpoints": {
            "/radio": "?id=<id|link>&n=25&fuente=youtubei|ytmusic -> IDs de la radio",
            "/buscar": "?q=<texto>&n=10 -> IDs y datos básicos de una búsqueda",
            "/id": "?url=<link> -> extrae el ID de un link",
            "/salud": "estado del servicio",
        },
        "autenticacion": "X-API-Key" if os.environ.get("API_KEY") else "ninguna",
    })


@app.get("/salud")
def salud():
    return jsonify({"ok": True})


@app.get("/id")
def sacar_id():
    video_id = parse_video_id(request.args.get("url") or request.args.get("id") or "")
    if not video_id:
        return error(400, "ENTRADA_INVALIDA", "No se encontró un ID de video válido.")
    return jsonify({"ok": True, "id": video_id})


@app.get("/radio")
def radio():
    video_id = parse_video_id(request.args.get("id") or request.args.get("url") or "")
    if not video_id:
        return error(400, "ENTRADA_INVALIDA",
                     "Envía 'id' (11 caracteres) o 'url' (link de YouTube) válidos.")
    n = entero("n", 25, 1, 50)
    elegida = (request.args.get("fuente") or "").strip().lower()
    if elegida and elegida not in FUENTES:
        return error(400, "FUENTE_INVALIDA", f"Fuente desconocida. Usa: {', '.join(FUENTES)}.")
    orden = [(elegida, FUENTES[elegida])] if elegida else list(FUENTES.items())

    errores = {}
    for nombre, funcion in orden:
        try:
            ids = funcion(video_id, n)
            if ids:
                r = jsonify({"ok": True, "semilla": video_id, "fuente": nombre,
                             "total": len(ids), "ids": ids})
                r.headers["Cache-Control"] = "no-store"  # la radio cambia en cada consulta
                return r
            errores[nombre] = "Sin resultados"
        except Exception as e:
            app.logger.warning("radio %s falló: %s", nombre, e)
            errores[nombre] = f"{type(e).__name__}: {str(e)[:300]}"
    return error(502, "RADIO_NO_DISPONIBLE", "No se pudo obtener la radio de este video.", errores)


@app.get("/buscar")
def buscar():
    q = (request.args.get("q") or "").strip()
    if not q:
        return error(400, "FALTA_BUSQUEDA", "Falta el parámetro 'q' con el texto a buscar.")
    n = entero("n", 10, 1, 25)
    try:
        from ytmusicapi import YTMusic
        encontrados = YTMusic().search(q, filter="videos", limit=n)
    except Exception as e:
        return error(502, "BUSQUEDA_FALLIDA", "No se pudo realizar la búsqueda.", f"{type(e).__name__}: {str(e)[:300]}")
    resultados = [{
        "id": e.get("videoId"),
        "titulo": e.get("title"),
        "canal": (e.get("artists") or [{}])[0].get("name"),
        "duracion": e.get("duration"),
    } for e in encontrados if e.get("videoId")][:n]
    r = jsonify({"ok": True, "consulta": q, "total": len(resultados), "resultados": resultados})
    r.headers["Cache-Control"] = "s-maxage=300, stale-while-revalidate"
    return r


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
