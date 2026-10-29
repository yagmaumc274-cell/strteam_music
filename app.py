import os
import re

import yt_dlp
from flask import Flask, Response, jsonify, render_template_string, request
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

app = Flask(__name__)
app.json.ensure_ascii = False

ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_ID_REGEX = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "format": "ba/b",
    "socket_timeout": 10,
}

# Clientes de YouTube a probar, en orden (None = el predeterminado de yt-dlp)
CLIENTES = [None, "tv", "web_safari", "mweb", "android_vr"]


def opciones_ydl():
    """Opciones base + cookies y proxy opcionales tomados de variables de entorno."""
    opts = dict(YDL_OPTS)
    cookies = os.environ.get("YT_COOKIES")  # contenido del cookies.txt (formato Netscape)
    if cookies:
        ruta = "/tmp/yt_cookies.txt"  # en Vercel solo /tmp es escribible
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(cookies)
        opts["cookiefile"] = ruta
    # YouTube exige un runtime de JavaScript (Deno) para resolver los formatos de audio.
    try:
        import deno  # paquete de PyPI que incluye el binario de Deno

        os.environ.setdefault("DENO_DIR", "/tmp/deno")  # en Vercel solo /tmp es escribible
        opts["js_runtimes"] = {"deno": {"path": deno.find_deno_bin()}}
        opts["remote_components"] = ["ejs:github"]
    except Exception:
        app.logger.warning("Deno no disponible: algunos formatos pueden faltar")
    proxy = os.environ.get("YT_PROXY")  # ej: http://usuario:clave@host:puerto
    if proxy:
        opts["proxy"] = proxy
    return opts


# (texto a buscar en el error, código, HTTP status, explicación)
REGLAS = [
    ("requested format is not available", "FORMATO_NO_DISPONIBLE", 502,
     "YouTube no entregó formatos de audio (suele faltar el runtime de JavaScript o yt-dlp está desactualizado)."),
    ("private video", "VIDEO_PRIVADO", 403, "El video es privado."),
    ("video unavailable", "VIDEO_NO_DISPONIBLE", 404, "El video no está disponible o no existe."),
    ("has been removed", "VIDEO_ELIMINADO", 404, "El video fue eliminado."),
    ("confirm your age", "RESTRICCION_EDAD", 403, "El video tiene restricción de edad."),
    ("sign in to confirm you", "BLOQUEO_BOT", 429, "YouTube detectó tráfico automatizado y pide iniciar sesión o cookies."),
    ("available in your country", "BLOQUEO_REGION", 451, "Este video está bloqueado en el país del servidor (Vercel). Cambia la región de la función a un país donde esté disponible."),
    ("not available in your country", "BLOQUEO_REGION", 451, "Video bloqueado en la región del servidor."),
    ("copyright", "DERECHOS_AUTOR", 451, "Video bloqueado por derechos de autor."),
    ("members-only", "SOLO_MIEMBROS", 403, "Video solo para miembros del canal."),
    ("live event will begin", "LIVE_NO_INICIADO", 409, "La transmisión en vivo aún no comienza."),
    ("timed out", "TIMEOUT", 504, "Tiempo de espera agotado al contactar YouTube."),
    ("unable to download webpage", "ERROR_RED", 502, "No se pudo conectar con YouTube."),
    ("http error 429", "DEMASIADAS_SOLICITUDES", 429, "Demasiadas solicitudes a YouTube."),
    ("http error 403", "ACCESO_DENEGADO", 403, "YouTube denegó el acceso."),
]


def parse_video_id(texto):
    """Acepta un ID de 11 caracteres o un link de YouTube (watch, youtu.be, shorts, embed)."""
    texto = (texto or "").strip()
    if ID_REGEX.match(texto):
        return texto
    m = URL_ID_REGEX.search(texto)
    return m.group(1) if m else None


def clasificar(e):
    msg = str(e).lower()
    for clave, codigo, status, explicacion in REGLAS:
        if clave in msg:
            return codigo, status, explicacion
    return "ERROR_NO_CLASIFICADO", 502, "Error no clasificado."


def error_payload(tipo, codigo, explicacion, detalle=None):
    return {"ok": False, "error": {"tipo": tipo, "codigo": codigo,
                                   "explicacion": explicacion, "detalle": detalle}}


def procesar(entrada):
    """Valida el ID, consulta YouTube y devuelve (status_http, dict_json)."""
    video_id = parse_video_id(entrada)
    if not video_id:
        return 400, error_payload(
            "ValidationError", "ENTRADA_INVALIDA",
            "Ingresa un ID de video (11 caracteres) o un link de YouTube válido.")
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        info, cliente = None, "default"
        ultimo_error = None
        # Si YouTube no entrega formatos con el cliente por defecto, se prueban otros.
        for cliente_prueba in CLIENTES:
            opts = opciones_ydl()
            if cliente_prueba:
                opts["extractor_args"] = {"youtube": {"player_client": [cliente_prueba]}}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)  # solo metadatos
                cliente = cliente_prueba or "default"
                break
            except DownloadError as e:
                ultimo_error = e
                if "requested format is not available" not in str(e).lower():
                    raise
        if info is None:
            raise ultimo_error
        if not info.get("url"):
            return 502, error_payload("AudioNotFound", "AUDIO_NO_ENCONTRADO",
                                      "No se encontró una URL de audio para este video.")
        return 200, {"ok": True, "data": {
            "id": info.get("id"),
            "titulo": info.get("title"),
            "canal": info.get("uploader"),
            "duracion_segundos": info.get("duration"),
            "vistas": info.get("view_count"),
            "fecha_subida": info.get("upload_date"),
            "miniatura": info.get("thumbnail"),
            "url_audio": info.get("url"),
            "cliente_youtube": cliente,
        }}
    except DownloadError as e:
        codigo, status, expl = clasificar(e)
        return status, error_payload("DownloadError", codigo, expl, str(e))
    except UnsupportedError as e:
        return 400, error_payload("UnsupportedError", "URL_NO_SOPORTADA", "La URL no es compatible.", str(e))
    except ExtractorError as e:
        return 502, error_payload("ExtractorError", "FALLO_EXTRACCION", "Falló la extracción de datos.", str(e))
    except Exception as e:
        app.logger.exception("Error inesperado")
        return 500, error_payload(type(e).__name__, "ERROR_INESPERADO", "Error inesperado.", str(e))


def duracion(seg):
    if not isinstance(seg, (int, float)):
        return "—"
    seg = int(seg)
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Extractor de audio</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --line:#2a2f3a; --txt:#e8eaf0; --mut:#9aa3b2; --ac:#4f8cff; --ok:#3ecf8e; --err:#ff6b6b; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f5f6f8; --card:#fff; --line:#dde1e8; --txt:#161a22; --mut:#5d6675; --ac:#2563eb; --ok:#0f9d63; --err:#d63c3c; }
  }
  * { box-sizing:border-box }
  body { margin:0; background:var(--bg); color:var(--txt); font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; padding:24px 16px }
  main { max-width:640px; margin:0 auto }
  h1 { font-size:1.4rem; margin:0 0 4px }
  p.sub { color:var(--mut); margin:0 0 20px }
  form { display:flex; gap:8px; flex-wrap:wrap }
  input[type=text] { flex:1 1 260px; padding:12px 14px; border-radius:10px; border:1px solid var(--line); background:var(--card); color:var(--txt); font-size:1rem }
  input[type=text]:focus { outline:2px solid var(--ac); border-color:transparent }
  button { padding:12px 20px; border:0; border-radius:10px; background:var(--ac); color:#fff; font-size:1rem; font-weight:600; cursor:pointer }
  .card { margin-top:20px; background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; overflow:hidden }
  .card.err { border-color:var(--err) }
  .card img { width:100%; border-radius:10px; display:block; margin-bottom:12px }
  .tag { display:inline-block; font-size:.75rem; font-weight:700; padding:2px 8px; border-radius:999px; margin-bottom:8px }
  .tag.ok { color:var(--ok); border:1px solid var(--ok) }
  .tag.err { color:var(--err); border:1px solid var(--err) }
  h2 { font-size:1.15rem; margin:0 0 8px }
  dl { display:grid; grid-template-columns:auto 1fr; gap:4px 14px; margin:0 }
  dt { color:var(--mut) } dd { margin:0; word-break:break-word }
  code { background:var(--bg); border:1px solid var(--line); border-radius:6px; padding:1px 6px; font-size:.85rem }
  audio { width:100%; margin-top:14px }
  details { margin-top:10px; color:var(--mut) }
  pre { white-space:pre-wrap; word-break:break-word; font-size:.8rem; background:var(--bg); padding:10px; border-radius:8px; border:1px solid var(--line) }
  footer { margin-top:28px; color:var(--mut); font-size:.85rem }
</style>
</head>
<body>
<main>
  <h1>🎵 Extractor de audio</h1>
  <p class="sub">Ingresa el ID o el link de un video de YouTube para obtener sus datos.</p>

  <form method="get" action="/">
    <input type="text" name="id" value="{{ entrada }}" placeholder="Ej: Q27iObu4lZc o https://youtu.be/Q27iObu4lZc"
           autocomplete="off" autofocus required>
    <button type="submit">Consultar</button>
  </form>

  {% if resultado %}
    {% if resultado.ok %}
      {% set d = resultado.data %}
      <section class="card">
        <span class="tag ok">✅ ÉXITO</span>
        {% if d.miniatura %}<img src="{{ d.miniatura }}" alt="Miniatura">{% endif %}
        <h2>{{ d.titulo }}</h2>
        <dl>
          <dt>Canal</dt><dd>{{ d.canal or "—" }}</dd>
          <dt>Duración</dt><dd>{{ dur }}</dd>
          <dt>Vistas</dt><dd>{{ "{:,}".format(d.vistas) if d.vistas else "—" }}</dd>
          <dt>Subido</dt><dd>{{ fecha }}</dd>
          <dt>ID</dt><dd><code>{{ d.id }}</code></dd>
          <dt>Endpoints</dt><dd><code>/audio/{{ d.id }}</code> · <code>/api/info?id={{ d.id }}</code></dd>
        </dl>
        <audio controls preload="none" src="{{ d.url_audio }}"></audio>
      </section>
    {% else %}
      {% set e = resultado.error %}
      <section class="card err">
        <span class="tag err">❌ ERROR · {{ e.tipo }}</span>
        <h2>{{ e.explicacion }}</h2>
        <dl>
          <dt>Código</dt><dd><code>{{ e.codigo }}</code></dd>
          <dt>HTTP</dt><dd>{{ status }}</dd>
        </dl>
        {% if e.detalle %}<details><summary>Detalle técnico</summary><pre>{{ e.detalle }}</pre></details>{% endif %}
      </section>
    {% endif %}
  {% endif %}

  <footer>API: <code>/audio/&lt;id&gt;</code> devuelve la URL del audio en texto · <code>/api/info?id=&lt;id&gt;</code> devuelve JSON.</footer>
</main>
</body>
</html>"""


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/")
def inicio():
    """Pide el ID/link primero; al enviarlo muestra los datos o el error."""
    entrada = (request.args.get("id") or request.args.get("url") or "").strip()
    resultado, status, dur, fecha = None, 200, "—", "—"
    if entrada:
        status, resultado = procesar(entrada)
        if resultado["ok"]:
            d = resultado["data"]
            dur = duracion(d["duracion_segundos"])
            f = d.get("fecha_subida") or ""
            fecha = f"{f[6:8]}/{f[4:6]}/{f[:4]}" if len(f) == 8 else "—"
    resp = Response(render_template_string(
        PAGINA, entrada=entrada, resultado=resultado, status=status, dur=dur, fecha=fecha),
        mimetype="text/html")
    return resp


@app.route("/audio/<video_id>")
def obtener_audio(video_id):
    """Compatible con la versión anterior: devuelve solo la URL del audio como texto."""
    if not ID_REGEX.fullmatch(video_id):
        return Response("ID no válido", status=400, mimetype="text/plain")
    status, body = procesar(video_id)
    if body["ok"]:
        return Response(body["data"]["url_audio"], mimetype="text/plain")
    return Response(body["error"]["explicacion"], status=status, mimetype="text/plain")


@app.route("/api/info")
def api_info():
    """Datos completos en JSON; en caso de fallo, tipo y causa del error."""
    status, body = procesar(request.args.get("id") or request.args.get("url") or "")
    resp = jsonify(body)
    resp.status_code = status
    return resp


@app.route("/debug")
def debug():
    """Diagnóstico: versiones y si Deno está disponible. No muestra cookies ni datos sensibles."""
    import subprocess
    out = {"yt_dlp": getattr(getattr(yt_dlp, "version", None), "__version__", "?"),
           "cookies_configuradas": bool(os.environ.get("YT_COOKIES")),
           "proxy_configurado": bool(os.environ.get("YT_PROXY")),
           "region_vercel": os.environ.get("VERCEL_REGION")}
    try:
        import deno
        ruta = deno.find_deno_bin()
        out["deno_ruta"] = ruta
        r = subprocess.run([ruta, "--version"], capture_output=True, text=True, timeout=10,
                           env={**os.environ, "DENO_DIR": "/tmp/deno"})
        out["deno_version"] = (r.stdout or r.stderr).strip().splitlines()[:1]
    except Exception as e:
        out["deno_error"] = f"{type(e).__name__}: {e}"
    vid = parse_video_id(request.args.get("id", ""))
    if vid:
        try:
            opts = opciones_ydl()
            opts.update({"format": None, "ignore_no_formats_error": True, "skip_download": True})
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            fmts = info.get("formats") or []
            out["formatos_total"] = len(fmts)
            out["formatos_audio"] = len([f for f in fmts if f.get("vcodec") == "none"])
            out["formatos_ejemplo"] = [f"{f.get('format_id')}:{f.get('ext')}:{f.get('format_note') or ''}" for f in fmts[:8]]
        except Exception as e:
            out["formatos_error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return jsonify(out)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
