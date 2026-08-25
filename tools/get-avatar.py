from os import environ
from pathlib import Path
from io import BytesIO
import re

import requests
from PIL import Image

PROSODY = Path(__file__).parent.parent / "prosody/data/avatar"
DOMAIN = environ['XMPP_DOMAIN']

IMAGE_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}


def dwn(url: str, destination: Path) -> Path:
    url = re.sub(r"=s\d+$", "", url)
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    with Image.open(BytesIO(response.content)) as image:
        image_format = image.format
        extension = IMAGE_EXTENSIONS.get(image_format)
        if extension is None:
            raise ValueError(f"Unsupported image format: {image_format}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    output = destination.with_name(destination.name + extension)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_bytes(response.content)
    temporary.replace(output)
    return output

def get_json(url: str):
    r = requests.get(url)
    r.raise_for_status()
    js = r.json()
    if not isinstance(js, dict):
        raise ValueError("Expected a dictionary")
    return js

DATA = get_json(environ['ROSTER_FIX'])

for k, v in DATA.items():
    if not isinstance(k, str):
        continue
    if "@" not in k and not k.endswith(f".{DOMAIN}"):
        continue
    if not isinstance(v, dict):
        continue
    avatar = v.get("avatar")
    if not isinstance(avatar, dict):
        continue
    custom = avatar.get("custom")
    default = avatar.get("default")
    if isinstance(custom, str):
        dwn(custom, PROSODY / "custom" / k)
    elif isinstance(default, str):
        dwn(default, PROSODY / "default" / k)