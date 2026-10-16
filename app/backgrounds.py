"""Studio sets for the presenter still.

Photo keeps the uploaded portrait. The other sets cut the person out with
the open-weight u2net human model and place them on a drawn studio plate.
The plate is the still Wan animates, so the set is in the picture.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 768

BASE_PROMPT = (
    "A presenter seated at a broadcast desk, speaking directly to the camera. "
    "Locked-off medium close-up. Calm, confident expression. Natural mouth shapes. "
    "Small head movement. Both hands rest on the desk. The presenter remains seated. "
    "Realistic skin, even broadcast lighting, sharp focus."
)

# wall top, wall bottom, desk, desk rim, light
SETS = {
    "photo": {
        "label": "Photo",
        "line": "Clean background, as in the portrait.",
    },
    "night": {
        "label": "Night studio",
        "colors": ((12, 18, 36), (32, 42, 68), (16, 14, 18), (196, 150, 88), (72, 58, 36)),
        "line": "The set is a dim evening studio with a deep blue wall, a warm key light, and a dark desk.",
    },
    "warm": {
        "label": "Warm studio",
        "colors": ((96, 62, 40), (154, 108, 72), (64, 40, 26), (230, 196, 142), (120, 78, 40)),
        "line": "The set is a warm wood studio with an amber wall, lamp light, and a honey-colored desk.",
    },
    "news": {
        "label": "News desk",
        "colors": ((44, 60, 80), (92, 112, 132), (206, 210, 214), (244, 246, 248), (70, 90, 112)),
        "line": "The set is a cool news studio with a grey-blue wall, even light, and a pale desk.",
    },
    "grey": {
        "label": "Soft grey",
        "colors": ((176, 176, 178), (124, 124, 128), (40, 40, 44), (214, 214, 216), (90, 90, 94)),
        "line": "The set is a plain soft-grey seamless backdrop with a low dark desk.",
    },
    "import": {
        "label": "Imported picture",
        "line": "The set behind the presenter is the imported picture.",
    },
}

_session = None


def prompt_for(background: str) -> str:
    spec = SETS[background]
    return f"{BASE_PROMPT} {spec['line']}"


def video_prompt(base: str | None, text: str, animate: bool) -> str | None:
    custom = " ".join(str(text or "").split())
    if len(custom) > 400:
        raise ValueError("Keep the background prompt to 400 characters.")
    parts = []
    if base:
        parts.append(base.rstrip())
    elif custom or animate:
        parts.append(BASE_PROMPT)
    if custom:
        parts.append(custom if custom.endswith(".") else custom + ".")
    if animate:
        parts.append(
            "The background moves gently behind the presenter: lights shift and the set has a slow living motion. "
            "The presenter stays seated. The camera stays locked. The face stays the same."
        )
    if not parts:
        return None
    return " ".join(parts)


ROOMS = {
    "photo": "a neutral broadcast studio with a dark desk and a plain dark wall",
    "night": "a dim evening studio with a deep blue wall, a warm key light, and a dark desk",
    "warm": "a warm wood studio with an amber wall, lamp light, and a honey-colored desk",
    "news": "a cool news studio with a grey-blue wall, even light, and a pale desk",
    "grey": "a plain soft-grey seamless backdrop with a low dark desk",
    "import": "a neutral broadcast studio with a dark desk and a plain dark wall",
}


def room_prompt(kind: str, text: str = "") -> str:
    if kind not in ROOMS:
        raise ValueError("Pick Photo, a studio set, or an imported background.")
    custom = " ".join(str(text or "").split())
    if len(custom) > 400:
        raise ValueError("Keep the background prompt to 400 characters.")
    if custom:
        return (
            f"{custom}. "
            "Empty scene, no people, no faces, no hands, no text, no logo, no watermark. "
            "Photorealistic, sharp focus."
        )
    return (
        "An empty photorealistic television studio, no people, no faces, no hands. "
        f"A locked-off view of {ROOMS[kind]}. "
        "The desk is empty. Sharp focus, no text, no logo, no watermark."
    )


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _plate(background: str) -> Image.Image:
    top, bottom, desk, rim, light = SETS[background]["colors"]
    desk_y = int(SIZE * 0.78)
    rows = []
    for y in range(SIZE):
        if y < desk_y:
            color = _lerp(top, bottom, y / max(desk_y - 1, 1))
        elif y < desk_y + 6:
            color = rim
        else:
            color = _lerp(desk, (0, 0, 0), 0.28 * (y - desk_y) / (SIZE - desk_y))
        rows.append(bytes(color) * SIZE)
    plate = Image.frombytes("RGB", (SIZE, SIZE), b"".join(rows))
    glow = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse([SIZE * 0.18, SIZE * 0.02, SIZE * 0.82, SIZE * 0.7], fill=light)
    glow = glow.filter(ImageFilter.GaussianBlur(72))
    return ImageChops.add(plate, glow)


def _cover(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    width, height = image.size
    scale = max(SIZE / width, SIZE / height)
    resized = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    left = (resized.width - SIZE) // 2
    upper = (resized.height - SIZE) // 2
    return resized.crop((left, upper, left + SIZE, upper + SIZE))


def _cutout_session():
    global _session
    if _session is None:
        from rembg import new_session

        _session = new_session("u2net_human_seg")
    return _session


def _cutout(plate_sized: Image.Image) -> Image.Image:
    from rembg import remove

    buf = BytesIO()
    plate_sized.save(buf, format="PNG")
    raw = remove(buf.getvalue(), session=_cutout_session(), alpha_matting=False)
    person = Image.open(BytesIO(raw)).convert("RGBA")
    alpha = person.getchannel("A")
    if alpha.getextrema()[1] < 16:
        raise ValueError("No person was found in that portrait. Use Photo, or a clearer picture.")
    person.putalpha(alpha.filter(ImageFilter.GaussianBlur(radius=0.8)))
    return person


def _open_image(raw: bytes, label: str) -> Image.Image:
    try:
        image = Image.open(BytesIO(raw))
        image.load()
    except Exception as exc:
        raise ValueError(f"The {label} file could not be read.") from exc
    return image


def prepare(portrait: bytes, background: str, plate: bytes | None = None) -> tuple[bytes, str | None]:
    """Return the still to animate, and a prompt when the set replaces the photo."""
    if background not in SETS:
        raise ValueError("Pick Photo, a studio set, or an imported background.")
    if background == "photo":
        return portrait, None
    if background == "import" and not plate:
        raise ValueError("Choose a background picture.")
    framed = _cover(_open_image(portrait, "portrait"))
    person = _cutout(framed)
    if background == "import":
        still = _cover(_open_image(plate, "background"))
    else:
        still = _plate(background)
    still.paste(person, (0, 0), person)
    out = BytesIO()
    still.save(out, format="PNG")
    return out.getvalue(), prompt_for(background)
