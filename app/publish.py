"""Send a finished take to YouTube, and open Rumble and Spotify.

YouTube has a public upload API. The file is sent with the user's own
Google login. Rumble and Spotify accept video only through their websites,
so those buttons open the official upload pages.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".secrets" / "youtube.json"
REDIRECT = "http://127.0.0.1:8765/api/publish/youtube/callback"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
RUMBLE_URL = "https://rumble.com/upload.php"
SPOTIFY_URL = "https://creators.spotify.com/"


def _load() -> dict:
    if not SECRETS.is_file():
        return {}
    try:
        return json.loads(SECRETS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(data: dict) -> None:
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    SECRETS.write_text(json.dumps(data), encoding="utf-8")


def status() -> dict:
    data = _load()
    return {
        "connected": bool(data.get("refresh_token")),
        "client_saved": bool(data.get("client_id") and data.get("client_secret")),
        "rumble": RUMBLE_URL,
        "spotify": SPOTIFY_URL,
    }


def start_connect(client_id: str, client_secret: str) -> str:
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if not client_id or not client_secret:
        raise ValueError("Paste the Google client id and client secret first.")
    saved = _load()
    saved["client_id"] = client_id
    saved["client_secret"] = client_secret
    _save(saved)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": UPLOAD_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return "https://accounts.google.com/o/oauth2/v2/auth?" + query


def finish_connect(code: str) -> str:
    saved = _load()
    if not saved.get("client_id") or not saved.get("client_secret"):
        raise ValueError("The Google client was not saved. Connect again from the page.")
    token = _token(
        {
            "code": code,
            "client_id": saved["client_id"],
            "client_secret": saved["client_secret"],
            "redirect_uri": REDIRECT,
            "grant_type": "authorization_code",
        }
    )
    if token.get("refresh_token"):
        saved["refresh_token"] = token["refresh_token"]
    saved["access_token"] = token.get("access_token", "")
    saved["expiry"] = time.time() + int(token.get("expires_in") or 0) - 30
    _save(saved)
    return "YouTube is connected. You can close this tab and return to the page."


def _token(form: dict) -> dict:
    raw = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=raw,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Google did not accept the login. {detail}") from exc


def _access_token() -> str:
    saved = _load()
    if not saved.get("refresh_token"):
        raise ValueError("Connect YouTube first.")
    if saved.get("access_token") and float(saved.get("expiry") or 0) > time.time():
        return saved["access_token"]
    token = _token(
        {
            "client_id": saved["client_id"],
            "client_secret": saved["client_secret"],
            "refresh_token": saved["refresh_token"],
            "grant_type": "refresh_token",
        }
    )
    saved["access_token"] = token["access_token"]
    saved["expiry"] = time.time() + int(token.get("expires_in") or 0) - 30
    _save(saved)
    return saved["access_token"]


def upload(path: Path, title: str, description: str, privacy: str) -> str:
    if privacy not in ("private", "unlisted", "public"):
        raise ValueError("Choose private, unlisted, or public.")
    title = " ".join(title.split())[:100] or "Podcast video"
    description = description.strip()[:5000]
    size = path.stat().st_size
    meta = json.dumps(
        {
            "snippet": {"title": title, "description": description, "categoryId": "22"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }
    ).encode("utf-8")
    query = urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status"})
    request = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?" + query,
        data=meta,
        method="POST",
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            location = response.headers.get("Location")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"YouTube refused the upload. {detail}") from exc
    if not location:
        raise RuntimeError("YouTube did not return an upload address.")
    with path.open("rb") as handle:
        body = handle.read()
    put = urllib.request.Request(
        location,
        data=body,
        method="PUT",
        headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
    )
    try:
        with urllib.request.urlopen(put, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"YouTube did not keep the file. {detail}") from exc
    video_id = result.get("id") or ""
    if not video_id:
        raise RuntimeError("YouTube accepted the call and returned no video id.")
    return f"https://studio.youtube.com/video/{video_id}/edit"


def reveal(folder: Path) -> None:
    os.startfile(folder)  # noqa: S606 - local Windows folder the user asked to open
