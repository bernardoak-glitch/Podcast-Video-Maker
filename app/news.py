"""Turn a topic into one spoken line.

Headlines come from the public Google News RSS feed. The sentence is written
by a local Ollama model. No partner model API is called.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "hermes3:8b"
MAX_WORDS = 20


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def headlines(topic: str, limit: int = 5) -> list[str]:
    query = urllib.parse.quote(f"{topic.strip()} when:1d")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    request = urllib.request.Request(url, headers={"User-Agent": "PodcastVideoMaker/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    found = []
    for item in root.findall("./channel/item"):
        title = re.sub(r"\s+", " ", (item.findtext("title") or "")).strip()
        if title:
            found.append(title)
        if len(found) >= limit:
            break
    return found


def _ask(prompt: str) -> str:
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError("Ollama is not answering on this PC. Start it, then try again.") from exc
    text = str(result.get("response") or "").strip().strip('"').strip()
    text = re.sub(r"\s+", " ", text)
    return text


def spoken_line(topic: str) -> dict:
    cleaned = re.sub(r"\s+", " ", topic).strip()
    if len(cleaned) < 3 or len(cleaned) > 160:
        raise ValueError("Type a short topic, such as news in ukraine war today.")
    found = headlines(cleaned)
    if not found:
        raise ValueError("No headlines came back for that search.")
    source = "\n".join(f"- {title}" for title in found)
    text = _ask(
        "Write one spoken sentence a presenter can say on camera. "
        "Use 12 to 20 words. Use only the headlines below. "
        "Do not add facts that are not in the headlines. "
        "Output the sentence only.\n\n"
        + source
    )
    if len(_words(text)) > MAX_WORDS:
        text = _ask(
            "Rewrite this as one spoken sentence of 12 to 18 words. "
            "Output the sentence only.\n\n"
            + text
        )
    words = _words(text)
    if len(words) > MAX_WORDS:
        text = " ".join(words[:MAX_WORDS]).rstrip(",;:") + "."
    if not text:
        raise RuntimeError("The local model returned an empty line.")
    return {"script": text, "headlines": found, "model": MODEL}
