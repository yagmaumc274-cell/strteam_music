
import re
import os
import yt_dlp
from flask import Flask, Response

app = Flask(__name__)

@app.route("/version")
def version():
    return yt_dlp.version.__version__

@app.route("/")
def inicio():
    return "API activa"

@app.route("/audio/<video_id>")
def obtener_audio(video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return Response("ID no válido", status=400, mimetype="text/plain")

    opciones = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
    }

    try:
        url = f"https://www.youtube.com/watch?v={video_id}"

        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=False)

        audio_url = info.get("url")

        if not audio_url:
            return Response("Audio no encontrado", status=502)

        return Response(audio_url, mimetype="text/plain")

    except Exception:
        app.logger.exception("Error al extraer audio")
        return Response("Error al obtener audio", status=502)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
