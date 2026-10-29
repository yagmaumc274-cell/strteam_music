import re
import sys

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_ID_REGEX = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})"
)

YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,          # Pon False para ver el proceso detallado
    "no_warnings": True,
    "extract_flat": False,
    "noplaylist": True,
}


def parse_video_id(texto: str) -> str | None:
    """Acepta un link de YouTube (watch, youtu.be, shorts, embed) o un ID de 11 caracteres."""
    texto = texto.strip()
    if ID_REGEX.match(texto):
        return texto
    m = URL_ID_REGEX.search(texto)
    return m.group(1) if m else None


def clasificar_error(e: Exception) -> str:
    """Devuelve una explicación legible según el tipo de error."""
    msg = str(e).lower()
    reglas = [
        ("private video", "El video es PRIVADO."),
        ("video unavailable", "El video NO ESTÁ DISPONIBLE (eliminado o inexistente)."),
        ("this video has been removed", "El video fue ELIMINADO."),
        ("sign in to confirm your age", "El video tiene RESTRICCIÓN DE EDAD y requiere iniciar sesión."),
        ("sign in to confirm you", "YouTube detectó tráfico automatizado (bot) y pide iniciar sesión / cookies."),
        ("not available in your country", "El video está BLOQUEADO EN TU REGIÓN (restricción geográfica)."),
        ("copyright", "El video fue bloqueado por DERECHOS DE AUTOR."),
        ("members-only", "El video es SOLO PARA MIEMBROS del canal."),
        ("live event will begin", "Es una transmisión en vivo que AÚN NO COMIENZA."),
        ("unable to download webpage", "Error de RED: no se pudo conectar con YouTube."),
        ("timed out", "Error de RED: tiempo de espera agotado."),
        ("http error 429", "Demasiadas solicitudes (HTTP 429). Espera un momento e inténtalo de nuevo."),
        ("http error 403", "Acceso denegado por YouTube (HTTP 403)."),
        ("http error 404", "Recurso no encontrado (HTTP 404)."),
    ]
    for clave, explicacion in reglas:
        if clave in msg:
            return explicacion
    return "Error no clasificado."


def extraer(video_id: str) -> None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"\n🔍 Consultando {url} ...")
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            # download=False: solo obtiene metadatos, no descarga el archivo
            info = ydl.extract_info(url, download=False)

        audio_url = info.get("url") or ""
        print("\n✅ ¡ÉXITO! yt-dlp está funcionando correctamente.")
        print(f"🆔 ID: {info.get('id')}")
        print(f"🎵 Título: {info.get('title')}")
        print(f"👤 Canal/Artista: {info.get('uploader')}")
        print(f"⏱️ Duración: {info.get('duration')} segundos")
        print(f"👁️ Vistas: {info.get('view_count')}")
        print(f"📅 Fecha de subida: {info.get('upload_date')}")
        print(f"🔗 URL de audio: {audio_url[:60]}{'...' if audio_url else 'no disponible'}")

    except DownloadError as e:
        print("\n❌ ERROR (DownloadError): yt-dlp no pudo obtener el video.")
        print(f"   Causa probable: {clasificar_error(e)}")
        print(f"   Detalle: {e}")
    except UnsupportedError as e:
        print("\n❌ ERROR (UnsupportedError): la URL no es compatible.")
        print(f"   Detalle: {e}")
    except ExtractorError as e:
        print("\n❌ ERROR (ExtractorError): falló la extracción de datos.")
        print(f"   Detalle: {e}")
    except (KeyError, TypeError, AttributeError) as e:
        print(f"\n❌ ERROR ({type(e).__name__}): la respuesta no tenía el formato esperado.")
        print(f"   Detalle: {e}")
    except KeyboardInterrupt:
        print("\n⛔ Operación cancelada por el usuario.")
    except Exception as e:  # cualquier otro fallo inesperado
        print(f"\n❌ ERROR INESPERADO ({type(e).__name__}).")
        print(f"   Detalle: {e}")


def main() -> None:
    print("=== Extractor de datos de YouTube (yt-dlp) ===")
    print("Pega un link o un ID de video (11 caracteres). Escribe 'salir' para terminar.\n")
    while True:
        try:
            entrada = input("🔗 Link o ID del video: ")
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Hasta luego.")
            sys.exit(0)

        if entrada.strip().lower() in {"salir", "exit", "q"}:
            print("👋 Hasta luego.")
            break

        video_id = parse_video_id(entrada)
        if not video_id:
            print("⚠️ Entrada inválida: no es un link de YouTube ni un ID de 11 caracteres.\n")
            continue

        extraer(video_id)
        print()


if __name__ == "__main__":
    main()
