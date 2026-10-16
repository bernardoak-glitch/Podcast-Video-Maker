"""Local page for a 5-second open-weights presenter take.

The page talks to a ComfyUI on this machine through comfy-api-proxy
(Comfy API v2) and comfy-sdk. It submits workflow/podcast_short.api.json.
It never calls Comfy Router or a partner model.
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile

from backgrounds import BASE_PROMPT, SETS, prepare, room_prompt, video_prompt
from news import spoken_line
from presenter import (
    EYES,
    FACIAL,
    GLASSES,
    HAIR,
    MEN_CLOTHES,
    MEN_STYLES,
    PEOPLE,
    ROLES,
    WOMEN_CLOTHES,
    WOMEN_STYLES,
    presenter_age,
    presenter_prompt,
)
import publish

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "workflow" / "podcast_short.api.json"
WAN_FULL = ROOT / "workflow" / "podcast_wan_full.api.json"
LTX_WORKFLOW = ROOT / "workflow" / "podcast_ltx.api.json"
LTX_FULL = ROOT / "workflow" / "podcast_ltx_full.api.json"
MINIMAX = ROOT / "workflow" / "podcast_minimax.api.json"
LTX_PERFORMANCE = (
    "A presenter seated at a broadcast desk, speaking directly to the camera. "
    "Locked-off medium close-up. Calm, confident expression. Natural mouth shapes that follow the speech. "
    "Small head movement. Both hands rest on the desk. The presenter remains seated. "
    "Realistic skin, even broadcast lighting, sharp focus, clean background."
)
WAN_PERFORMANCE = (
    "A presenter seated at a broadcast desk, speaking directly to the camera. "
    "Locked-off medium close-up. Calm, confident expression. Natural mouth shapes. "
    "Small head movement. Both hands rest on the desk. The presenter remains seated. "
    "Realistic skin, even broadcast lighting, sharp focus, clean background."
)
VIDEO_MODELS = {
    "ltx-q3": {
        "file": LTX_WORKFLOW,
        "unet": "LTX-2.5-Distilled-Q3_K_M.gguf",
        "performance": LTX_PERFORMANCE,
        "log": "Queued. LTX 2.5 Distilled Q3, the 12 GB GGUF. The full LTX checkpoint is not loaded.",
    },
    "ltx": {
        "file": LTX_FULL,
        "unet": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
        "performance": LTX_PERFORMANCE,
        "log": "Queued. LTX 2.5 Distilled, the full checkpoint. It needs a larger card than the Q3 GGUF.",
    },
    "wan": {
        "file": WORKFLOW,
        "unet": "wan2.2_s2v_14B_fp8_scaled.safetensors",
        "performance": WAN_PERFORMANCE,
        "log": "Queued. Wan 2.2 speech fp8, 4 steps, no LightX2V LoRA.",
    },
    "wan-full": {
        "file": WAN_FULL,
        "unet": "wan2.2_s2v_14B_bf16.safetensors",
        "performance": WAN_PERFORMANCE,
        "log": "Queued. Wan 2.2 speech bf16, 20 steps, no LightX2V LoRA. It needs a larger card than the fp8 pass.",
    },
    "minimax": {
        "file": MINIMAX,
        "unet": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "prompt_input": "prompt",
        "log": "Queued. MiniMax H3 image to video, 8-step turbo, open weights. The line is in the prompt and the model makes the soundtrack. It needs the H3 checkpoint and a larger card.",
    },
}
PRESENTER = ROOT / "workflow" / "presenter_still.api.json"
PRESENTER_ROOM = ROOT / "workflow" / "presenter_room.api.json"
PRESENTER_BOTH = ROOT / "workflow" / "presenter_both.api.json"
STATIC = Path(__file__).resolve().parent / "static" / "index.html"
OUTPUTS = ROOT / "outputs"
HOST = "127.0.0.1"
PORT = 8765
PROXY = "http://127.0.0.1:8189"
def take_seconds(model: str, raw) -> int:
    if model not in {"ltx-q3", "ltx"}:
        return 5
    if isinstance(raw, bool) or isinstance(raw, float):
        raise ValueError("Pick a length from 5 to 10 seconds.")
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Pick a length from 5 to 10 seconds.") from None
    if seconds < 5 or seconds > 10:
        raise ValueError("Pick a length from 5 to 10 seconds.")
    return seconds


def word_cap(seconds: int) -> int:
    return seconds * 4


def with_spoken_line(motion: str, script: str) -> str:
    line = script.strip().rstrip(".")
    text = motion.strip()
    if text and not text.endswith("."):
        text += "."
    return f"{text} The presenter says this line once: {line}."


def ltx_frames(seconds: int) -> int:
    target = round(seconds * 24)
    base = ((target - 1) // 8) * 8 + 1
    higher = base + 8
    if abs(higher - target) < abs(base - target):
        return higher
    return base
MAX_PORTRAIT_BYTES = 12_000_000
VOICES = (
    "bf_emma",
    "bf_alice",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_george",
    "bm_lewis",
    "bm_fable",
)

_lock = threading.Lock()
_job = {
    "status": "idle",
    "message": "Ready.",
    "lines": [],
    "video": None,
    "error": None,
}


def _set(**fields):
    with _lock:
        _job.update(fields)


def _log(line: str):
    with _lock:
        _job["lines"] = (_job["lines"] + [line])[-40:]
        _job["message"] = line


def _snapshot():
    with _lock:
        return dict(_job)


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "take"


def _busy() -> bool:
    with _lock:
        return _job["status"] == "running"


def _claim():
    with _lock:
        if _job["status"] == "running":
            return False
        _job.update(status="running", message="Starting.", lines=[], video=None, error=None)
        return True


def _release_idle():
    _set(status="idle", message="Ready.", lines=[], video=None, error=None)


def _temp_image(raw: bytes) -> str:
    handle = NamedTemporaryFile(suffix=".png", delete=False)
    handle.write(raw)
    handle.close()
    return handle.name


def _presenter_png(choices: dict, portrait: bytes | None = None, plate: bytes | None = None) -> bytes:
    if not os.environ.get("COMFY_BASE_URL", "").strip():
        os.environ["COMFY_BASE_URL"] = PROXY
    from comfy_sdk import Comfy

    paths = []
    if portrait and plate:
        graph = PRESENTER_BOTH
        scene = "both"
        note = "Drawing the start frame from the person and the imported picture. Flux 2. Four steps. No LoRA."
    elif plate:
        graph = PRESENTER_ROOM
        scene = "room"
        note = "Drawing the start frame in the imported picture. Flux 2. Four steps. No LoRA."
    else:
        graph = PRESENTER
        scene = "plain"
        note = "Drawing the presenter with Flux 2 text to image. Four steps. No LoRA."
    try:
        client = Comfy(client_info="podcast-video-maker-workflow")
        workflow = client.workflows.from_file(str(graph))
        workflow.set_input("4", "text", presenter_prompt(**choices, scene=scene))
        workflow.set_input("10", "noise_seed", random.randint(1, 2**31 - 1))
        if portrait and plate:
            paths.append(_temp_image(portrait))
            paths.append(_temp_image(plate))
            workflow.set_input("14", "image", client.assets.from_file(paths[0]))
            workflow.set_input("15", "image", client.assets.from_file(paths[1]))
        elif plate:
            paths.append(_temp_image(plate))
            workflow.set_input("14", "image", client.assets.from_file(paths[0]))
        _log(note)
        job = client.submit(workflow)
        job.result()
        outputs = list(job.get_outputs("13") or job.outputs)
        images = [item for item in outputs if getattr(item, "type", "") == "image"] or outputs
        if not images:
            raise RuntimeError("Flux 2 finished and returned no still.")
        dest = OUTPUTS / "presenter_still.png"
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        images[0].to_file(str(dest))
        return dest.read_bytes()
    finally:
        for path in paths:
            Path(path).unlink(missing_ok=True)


def _room_png(prompt: str) -> bytes:
    if not os.environ.get("COMFY_BASE_URL", "").strip():
        os.environ["COMFY_BASE_URL"] = PROXY
    from comfy_sdk import Comfy

    client = Comfy(client_info="podcast-video-maker-workflow")
    workflow = client.workflows.from_file(str(PRESENTER))
    workflow.set_input("4", "text", prompt)
    workflow.set_input("10", "noise_seed", random.randint(1, 2**31 - 1))
    _log("Drawing an empty studio with Flux 2. Four steps. No LoRA.")
    job = client.submit(workflow)
    job.result()
    outputs = list(job.get_outputs("13") or job.outputs)
    images = [item for item in outputs if getattr(item, "type", "") == "image"] or outputs
    if not images:
        raise RuntimeError("Flux 2 finished and returned no background.")
    dest = OUTPUTS / "background_still.png"
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    images[0].to_file(str(dest))
    return dest.read_bytes()


def _plate_bytes(payload: dict, key: str = "background_image", label: str = "background") -> bytes | None:
    raw = str(payload.get(key) or "")
    if not raw:
        return None
    try:
        plate = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError(f"The {label} file could not be read.") from exc
    if not plate or len(plate) > MAX_PORTRAIT_BYTES:
        raise ValueError(f"Use a {label} picture under 12 MB.")
    return plate


def _run(
    script: str,
    voice: str,
    portrait: bytes,
    suffix: str,
    background: str,
    plate: bytes | None,
    model: str,
    room_note: str,
    animate: bool,
    seconds: int,
):
    _set(status="running", message="Sending the take.", lines=[], video=None, error=None)
    path = None
    try:
        if background != "photo":
            _log("Cutting the portrait out and placing the set. The first time downloads the cutout model.")
        still, prompt = prepare(portrait, background, plate)
        prompt = video_prompt(prompt, room_note, animate)
        if background != "photo":
            suffix = ".png"
            portrait = still
        if not os.environ.get("COMFY_BASE_URL", "").strip():
            os.environ["COMFY_BASE_URL"] = PROXY
        try:
            from comfy_sdk import Comfy, Progress, StatusChange
        except ImportError as exc:
            raise RuntimeError(
                "comfy-sdk is not installed. From this repo run: pip install -r requirements.txt"
            ) from exc

        OUTPUTS.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(portrait)
            path = handle.name

        spec = VIDEO_MODELS[model]
        client = Comfy(client_info="podcast-video-maker-workflow")
        workflow = client.workflows.from_file(str(spec["file"]))
        portrait_asset = client.assets.from_file(path)
        workflow.set_input("1", "unet_name", spec["unet"])
        workflow.set_input("7", "image", portrait_asset)
        if spec.get("prompt_input") == "prompt":
            motion = (prompt or BASE_PROMPT).strip()
            if not motion.endswith("."):
                motion += "."
            line = script.strip().rstrip(".")
            workflow.set_input(
                "8",
                "prompt",
                f"{motion} The presenter says this line once: {line}. "
                "Audio is only that spoken line in a clear voice, with no music and no other voices.",
            )
        else:
            workflow.set_input("25", "text", script)
            workflow.set_input("24", "speaker_name", voice)
            motion = prompt or spec["performance"]
            workflow.set_input("8", "text", with_spoken_line(motion, script))
        if model in {"ltx-q3", "ltx"}:
            frames = ltx_frames(seconds)
            workflow.set_input("13", "length", frames)
            workflow.set_input("26", "duration", round(frames / 24, 2))
            _log(f"LTX length is {seconds} seconds, {frames} frames, up to {word_cap(seconds)} words.")
        if animate:
            _log("The background will move behind the seated presenter.")
        _log(spec["log"])

        job = client.submit(workflow)
        try:
            for event in job.events():
                if isinstance(event, Progress):
                    message = getattr(event, "message", "") or "sampling"
                    value = getattr(event, "value", None)
                    if isinstance(value, (int, float)):
                        _log(f"{value:.0%} {message}")
                    else:
                        _log(str(message))
                elif isinstance(event, StatusChange):
                    _log(f"Status: {getattr(event, 'status', '')}")
        except Exception as exc:
            _log(f"Progress stream closed ({exc}). Waiting for the finished job.")

        job.result()
        outputs = list(job.get_outputs("23") or job.outputs)
        videos = [item for item in outputs if getattr(item, "type", "") == "video"] or outputs
        if not videos:
            raise RuntimeError("The job finished and returned no video from node 23.")
        filename = _safe_name(getattr(videos[0], "name", "") or f"{job.id}.mp4")
        if not filename.lower().endswith((".mp4", ".webm", ".mkv", ".mov")):
            filename += ".mp4"
        dest = OUTPUTS / filename
        videos[0].to_file(str(dest))
        _set(
            status="done",
            message="Take ready.",
            video=f"/outputs/{dest.name}",
            error=None,
        )
    except ValueError as exc:
        _set(status="error", message="The take failed.", error=str(exc))
    except Exception as exc:
        _log(traceback.format_exc().splitlines()[-1])
        _set(status="error", message="The take failed.", error=str(exc))
    finally:
        if path:
            Path(path).unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self._json(200, _snapshot())
            return
        if path == "/api/publish/youtube/status":
            self._json(200, publish.status())
            return
        if path == "/api/publish/youtube/callback":
            from urllib.parse import parse_qs, urlparse

            code = (parse_qs(urlparse(self.path).query).get("code") or [""])[0]
            try:
                message = publish.finish_connect(code)
            except Exception as exc:
                message = str(exc)
            from html import escape

            page = (
                "<!DOCTYPE html><html><body style=\"font-family:sans-serif;background:#101218;color:#f4f1ea;padding:32px\">"
                f"<p>{escape(message)}</p></body></html>"
            ).encode("utf-8")
            self._send(200, page, "text/html; charset=utf-8")
            return
        if path.startswith("/outputs/"):
            name = Path(path).name
            target = (OUTPUTS / name).resolve()
            if target.parent != OUTPUTS.resolve() or not target.is_file():
                self._json(404, {"error": "No file."})
                return
            kind = "video/mp4"
            if target.suffix.lower() == ".webm":
                kind = "video/webm"
            self._send(200, target.read_bytes(), kind)
            return
        self._json(404, {"error": "Not found."})

    def _preview(self, portrait: bytes, background: str, plate: bytes | None):
        if _snapshot()["status"] == "running":
            self._json(409, {"error": "A take is running. The set preview waits until it finishes."})
            return
        if background == "photo":
            self._json(200, {"background": "photo"})
            return
        try:
            still, _prompt = prepare(portrait, background, plate)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        except Exception as exc:
            self._json(500, {"error": str(exc)})
            return
        self._json(200, {"background": background, "image": base64.b64encode(still).decode("ascii")})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in (
            "/api/generate",
            "/api/background",
            "/api/room",
            "/api/presenter",
            "/api/line",
            "/api/publish/youtube/start",
            "/api/publish/youtube",
            "/api/publish/reveal",
        ):
            self._json(404, {"error": "Not found."})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 36_000_000:
            self._json(400, {"error": "Send a portrait and a short script."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"error": "The form body was not JSON."})
            return

        if path == "/api/publish/youtube/start":
            try:
                url = publish.start_connect(
                    str(payload.get("client_id") or ""),
                    str(payload.get("client_secret") or ""),
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"url": url})
            return
        if path == "/api/publish/reveal":
            try:
                publish.reveal(OUTPUTS)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, {"ok": True})
            return
        if path == "/api/publish/youtube":
            name = Path(str(payload.get("file") or "")).name
            target = (OUTPUTS / name).resolve()
            if target.parent != OUTPUTS.resolve() or not target.is_file():
                self._json(400, {"error": "That take is not in the output folder."})
                return
            try:
                watch = publish.upload(
                    target,
                    str(payload.get("title") or ""),
                    str(payload.get("description") or ""),
                    str(payload.get("privacy") or "private"),
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, {"url": watch})
            return
        if path == "/api/line":
            topic = str(payload.get("topic") or "")
            if _busy():
                self._json(409, {"error": "A take is already running."})
                return
            try:
                seconds = take_seconds(str(payload.get("model") or "ltx-q3"), payload.get("seconds", 5))
                result = spoken_line(topic, seconds)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, result)
            return
        if path == "/api/room":
            kind = str(payload.get("background") or "photo")
            try:
                prompt = room_prompt(kind, str(payload.get("prompt") or ""))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            if not _claim():
                self._json(409, {"error": "A take is already running."})
                return
            try:
                png = _room_png(prompt)
            except Exception as exc:
                _set(status="error", message="The background failed.", error=str(exc))
                self._json(500, {"error": str(exc)})
                return
            _release_idle()
            self._json(200, {"image": base64.b64encode(png).decode("ascii")})
            return
        if path == "/api/presenter":
            choices = {
                "role": str(payload.get("role") or ""),
                "person": str(payload.get("person") or ""),
                "wardrobe": str(payload.get("wardrobe") or ""),
                "hair": str(payload.get("hair") or ""),
                "style": str(payload.get("style") or ""),
                "eyes": str(payload.get("eyes") or ""),
                "glasses": str(payload.get("glasses") or "none"),
                "facial": str(payload.get("facial") or "none"),
            }
            allowed = {
                "role": ROLES,
                "person": PEOPLE,
                "wardrobe": MEN_CLOTHES if choices["person"] == "man" else WOMEN_CLOTHES,
                "hair": HAIR,
                "style": MEN_STYLES if choices["person"] == "man" else WOMEN_STYLES,
                "eyes": EYES,
                "glasses": GLASSES,
                "facial": FACIAL,
            }
            if any(choices[key] not in options for key, options in allowed.items()):
                self._json(400, {"error": "Pick the presenter look from the lists."})
                return
            try:
                choices["age"] = str(presenter_age(payload.get("age")))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            try:
                plate = _plate_bytes(payload)
                portrait = _plate_bytes(payload, "portrait", "portrait")
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            if not _claim():
                self._json(409, {"error": "A take is already running."})
                return
            try:
                png = _presenter_png(choices, portrait, plate)
            except Exception as exc:
                _set(status="error", message="The presenter failed.", error=str(exc))
                self._json(500, {"error": str(exc)})
                return
            _release_idle()
            self._json(200, {"image": base64.b64encode(png).decode("ascii")})
            return
        script = str(payload.get("script") or "").strip()
        voice = str(payload.get("voice") or "bf_emma")
        background = str(payload.get("background") or "photo")
        portrait_b64 = str(payload.get("portrait") or "")
        if background not in SETS:
            self._json(400, {"error": "Pick Photo, a studio set, or an imported background."})
            return
        try:
            plate = _plate_bytes(payload)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        if background == "import" and plate is None:
            self._json(400, {"error": "Choose a background picture."})
            return
        if path == "/api/background":
            try:
                portrait = base64.b64decode(portrait_b64, validate=True)
            except Exception:
                self._json(400, {"error": "The portrait file could not be read."})
                return
            if not portrait or len(portrait) > MAX_PORTRAIT_BYTES:
                self._json(400, {"error": "Use a portrait under 12 MB."})
                return
            self._preview(portrait, background, plate)
            return
        model = str(payload.get("model") or "ltx-q3")
        if model not in VIDEO_MODELS:
            self._json(400, {"error": "Pick LTX 2.5 Distilled Q3, LTX 2.5 full, Wan 2.2 speech, Wan 2.2 full, or MiniMax H3."})
            return
        if voice not in VOICES:
            self._json(400, {"error": "Pick Emma, Alice, Isabella, or Lily."})
            return
        try:
            seconds = take_seconds(model, payload.get("seconds", 5))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        cap = word_cap(seconds)
        if _words(script) == 0 or _words(script) > cap:
            self._json(400, {"error": f"Use 1 to {cap} words. This take is {seconds} seconds."})
            return
        try:
            portrait = base64.b64decode(portrait_b64, validate=True)
        except Exception:
            self._json(400, {"error": "The portrait file could not be read."})
            return
        if not portrait or len(portrait) > MAX_PORTRAIT_BYTES:
            self._json(400, {"error": "Use a portrait under 12 MB."})
            return
        room_note = " ".join(str(payload.get("prompt") or "").split())
        if len(room_note) > 400:
            self._json(400, {"error": "Keep the background prompt to 400 characters."})
            return
        animate = payload.get("animate") is True
        suffix = ".png"
        name = str(payload.get("filename") or "").lower()
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            if name.endswith(ext):
                suffix = ".jpg" if ext == ".jpeg" else ext
                break

        if not _claim():
            self._json(409, {"error": "A take is already running."})
            return
        threading.Thread(
            target=_run,
            args=(script, voice, portrait, suffix, background, plate, model, room_note, animate, seconds),
            daemon=True,
        ).start()
        self._json(202, {"status": "running"})


def main():
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Podcast Video Maker is at http://{HOST}:{PORT}")
    print(f"Comfy proxy expected at {os.environ.get('COMFY_BASE_URL') or PROXY}")
    server.serve_forever()


if __name__ == "__main__":
    main()
