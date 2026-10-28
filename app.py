import json
import yt_dlp

# URL de prueba (un video de música corto o público)
TEST_URL = "https://www.youtube.com/watch?v=Q27iObu4lZc"

ydl_opts = {
    "format": "bestaudio/best",
    "quiet": False,  # Muestra el proceso detallado en la consola
    "no_warnings": False,
    "extract_flat": False,  # Extrae la información completa
}

print("🔍 Iniciando prueba con yt-dlp...")

try:
  with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    # extract_info con download=False solo obtiene metadatos sin descargar el archivo
    info = ydl.extract_info(TEST_URL, download=False)

    print("\n✅ ¡ÉXITO! yt-dlp está funcionando correctamente.")
    print(f"🎵 Título: {info.get('title')}")
    print(f"👤 Canal/Artista: {info.get('uploader')}")
    print(f"⏱️ Duración: {info.get('duration')} segundos")
    print(f"🔗 URL de audio obtenida: {info.get('url')[:60]}...")

except Exception as e:
  print("\n❌ ERROR: yt-dlp falló al obtener información.")
  print(" Detalle del error:")
  print(e)
