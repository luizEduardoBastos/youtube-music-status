"""
update_card.py — standalone script (sem Flask).
Executado pelo GitHub Actions periodicamente via cron.
"""

import base64
import os
import re
import sys
from io import BytesIO
from threading import Lock

from colorthief import ColorThief
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, storage
from PIL import Image
import requests
from ytmusicapi import YTMusic


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

load_dotenv()

upload_lock = Lock()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Autenticação do YouTube Music.
# Em produção (GitHub Actions) o conteúdo do header vem de uma secret
# gravada num arquivo temporário pelo workflow (veja youtube.yml).
YTMUSIC_BROWSER = os.getenv("YTMUSIC_BROWSER")          # caminho para o arquivo JSON
ytmusic = YTMusic(YTMUSIC_BROWSER)

# Firebase
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS")   # caminho para o JSON da service account
FIREBASE_BUCKET       = os.getenv("FIREBASE_BUCKET")        # ex: meu-projeto.appspot.com

cred = credentials.Certificate(FIREBASE_CREDENTIALS)
firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_BUCKET})

# Temas disponíveis (adicione mais conforme necessário)
THEMES = [
    {
        "name"         : "Theme_Card_HTML",
        "svg_template" : os.path.join(BASE_DIR, "themes", "Theme_Card_HTML.html"),
        "svg_output"   : os.path.join(BASE_DIR, "themes", "Theme_Card_HTML_UPDATED.svg"),
        "blob_name"    : "listening-on-ytmusic.svg",
        "title_class"  : "artist",
        "artist_class" : "song",
        "has_bars"     : True,
    },
]

# Arquivo de estado simples para evitar re-uploads desnecessários.
# No GitHub Actions o workspace é recriado a cada run, então esse arquivo
# não persiste entre execuções — isso é intencional: sempre processamos a
# música mais recente, mas o check abaixo ainda evita uploads duplos
# dentro da mesma execução (caso o script seja chamado mais de uma vez).
STATE_FILE = os.path.join(BASE_DIR, ".last_video_id")


# ---------------------------------------------------------------------------
# Estado entre runs (opcional — útil para testes locais)
# ---------------------------------------------------------------------------

def read_last_video_id() -> str | None:
    try:
        with open(STATE_FILE, "r") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def write_last_video_id(video_id: str) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(video_id)


# ---------------------------------------------------------------------------
# Helpers de imagem
# ---------------------------------------------------------------------------

def download_and_resize_image_base64(image_url: str, size: tuple = (300, 300)) -> str:
    response = requests.get(image_url, timeout=10)
    response.raise_for_status()
    img = Image.open(BytesIO(response.content)).resize(size, Image.LANCZOS)
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode("utf-8")


def get_dominant_color_from_thumbnail(thumbnail_url: str) -> tuple:
    response = requests.get(thumbnail_url, timeout=10)
    response.raise_for_status()
    return ColorThief(BytesIO(response.content)).get_color(quality=1)


def rgb_to_hex(rgb: tuple) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


# ---------------------------------------------------------------------------
# Helpers de SVG / HTML
# ---------------------------------------------------------------------------

def escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def safe_sub(class_name: str, new_text: str, content: str) -> str:
    def replacer(m):
        return m.group(1) + new_text
    return re.sub(
        r'(class="' + class_name + r'"[^>]*>)[^<]*',
        replacer,
        content,
    )


def overwrite_bar_color(svg_file: str, output_file: str, new_color: str) -> None:
    with open(svg_file, "r", encoding="utf-8") as f:
        content = f.read()

    style_block = f""".bar {{
    background: {new_color};
    bottom: 1px;
    height: 3px;
    position: absolute;
    width: 3px;
    animation: sound 0ms -800ms linear infinite alternate;
}}"""

    updated = re.sub(r"\.bar\s*\{[^}]*\}", style_block, content)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"  ↳ cor das barras atualizada para {new_color}")


def update_svg(
    svg_file: str,
    output_file: str,
    song_title: str,
    artist_name: str,
    thumbnail_url: str,
    hex_color: str,
    title_class: str,
    artist_class: str,
    has_bars: bool,
) -> None:
    with open(svg_file, "r", encoding="utf-8") as f:
        content = f.read()

    base64_thumbnail = download_and_resize_image_base64(thumbnail_url)

    content = safe_sub(title_class,  escape_xml(song_title),  content)
    content = safe_sub(artist_class, escape_xml(artist_name), content)

    parts = content.split('class="thumb"', 1)
    if len(parts) == 2:
        after_thumb = re.sub(
            r'src="[^"]*"', f'src="{base64_thumbnail}"', parts[1], count=1
        )
        content = parts[0] + 'class="thumb"' + after_thumb

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)

    if has_bars:
        overwrite_bar_color(output_file, output_file, hex_color)


# ---------------------------------------------------------------------------
# Upload para o Firebase Storage
# ---------------------------------------------------------------------------

def upload_to_firebase(bucket, blob_name: str, local_file: str) -> str:
    with upload_lock:
        blob = bucket.blob(blob_name)
        try:
            blob.delete()
        except Exception:
            pass

        blob.upload_from_filename(local_file, content_type="image/svg+xml")
        blob.cache_control = "no-cache, no-store, must-revalidate"
        blob.patch()

    print(f"  ↳ upload concluído → {blob.public_url}")
    return blob.public_url


# ---------------------------------------------------------------------------
# Entrypoint principal
# ---------------------------------------------------------------------------

def main() -> None:
    print("🎵 Buscando histórico do YouTube Music…")
    recent_songs = ytmusic.get_history()

    if not recent_songs:
        print("⚠️  Nenhum histórico encontrado. Encerrando.")
        sys.exit(0)

    recent_song_vid_id = recent_songs[0]["videoId"]
    last_vid_id        = read_last_video_id()

    if recent_song_vid_id == last_vid_id:
        print(f"✅ Mesma música já processada ({recent_song_vid_id}). Nada a fazer.")
        sys.exit(0)

    # Dados da música
    recent_song        = ytmusic.get_song(recent_song_vid_id)
    song_title         = recent_songs[0]["title"]
    artist_name        = recent_song["videoDetails"]["author"]
    thumb_url          = recent_song["videoDetails"]["thumbnail"]["thumbnails"][-1]["url"]

    print(f"🎧 Música  : {song_title}")
    print(f"👤 Artista : {artist_name}")

    dominant_color = get_dominant_color_from_thumbnail(thumb_url)
    hex_color      = rgb_to_hex(dominant_color)
    print(f"🎨 Cor dominante: {hex_color}")

    bucket = storage.bucket(FIREBASE_BUCKET)

    for theme in THEMES:
        print(f"\n📐 Processando tema: {theme['name']}")
        update_svg(
            svg_file      = theme["svg_template"],
            output_file   = theme["svg_output"],
            song_title    = song_title,
            artist_name   = artist_name,
            thumbnail_url = thumb_url,
            hex_color     = hex_color,
            title_class   = theme["title_class"],
            artist_class  = theme["artist_class"],
            has_bars      = theme["has_bars"],
        )
        upload_to_firebase(bucket, theme["blob_name"], theme["svg_output"])

    write_last_video_id(recent_song_vid_id)
    print(f"\n✔️  Concluído para video_id: {recent_song_vid_id}")


if __name__ == "__main__":
    main()