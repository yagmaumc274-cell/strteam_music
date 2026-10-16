
import os
import re
from flask import Flask, jsonify
import yt_dlp

app = Flask(__name__)


@app.route("/", methods=["GET"])
def inicio():
    return jsonify({
        "estado": "activo",
        "mensaje": "API de audio funcionando"
    })


@app.route("/audio/<video_id>", methods=["GET"])
def obtener_audio(video_id):
    video_id = video_id.strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return jsonify({"error": "ID de video no válido"}), 400

    url = f"https://www.youtube.com/watch?v={video_id}"

    opciones = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "extractor_args": {
            "youtube": {
                "player_client": ["tv"]
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=False)

        audio_url = info.get("url")

        if not audio_url:
            return jsonify({
                "error": "No se encontró la URL del audio"
            }), 502

        return jsonify({
            "titulo": info.get("title", "Desconocido"),
            "audio_url": audio_url
        })

    except Exception as error:
        app.logger.exception("Error al obtener el audio")
        return jsonify({"error": str(error)}), 502


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=puerto)
