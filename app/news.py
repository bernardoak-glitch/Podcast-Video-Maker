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


def script_budget(seconds: int) -> tuple[int, int]:
    """Return the comfortable word count and the hard cap for a take length."""
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 5 or seconds > 10:
        raise ValueError("Pick a length from 5 to 10 seconds.")
    return round(seconds * 2.4), seconds * 4
WINDOWS = (
    ("today", " when:1d"),
    ("this week", " when:7d"),
    ("recent", ""),
)
STOP = {
    "about",
    "after",
    "all",
    "also",
    "and",
    "are",
    "before",
    "but",
    "can",
    "day",
    "days",
    "for",
    "from",
    "had",
    "has",
    "have",
    "her",
    "his",
    "how",
    "into",
    "its",
    "just",
    "latest",
    "may",
    "more",
    "news",
    "not",
    "our",
    "out",
    "over",
    "said",
    "says",
    "she",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "these",
    "they",
    "this",
    "those",
    "today",
    "tonight",
    "update",
    "very",
    "was",
    "week",
    "were",
    "what",
    "when",
    "where",
    "who",
    "why",
    "will",
    "with",
    "year",
    "years",
    "you",
    "your",
}


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _content_words(text: str) -> set[str]:
    found = set()
    for word in re.findall(r"[A-Za-z0-9']+", text.lower()):
        if word in STOP or word.isdigit() or len(word) < 2:
            continue
        found.add(word)
    return found


def _overlaps(need: set[str], text: str) -> bool:
    have = _content_words(text)
    if need & have:
        return True
    for left in need:
        if len(left) < 4:
            continue
        for right in have:
            if len(right) >= 4 and left[:4] == right[:4]:
                return True
    return False


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if head and len(tail) <= 40 and not re.search(r"[.!?]", tail):
            title = head.strip()
    return title


def _fetch(topic: str, window: str, limit: int) -> list[str]:
    query = urllib.parse.quote(f"{topic.strip()}{window}")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    request = urllib.request.Request(url, headers={"User-Agent": "PodcastVideoMaker/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Headlines could not be loaded. Check the connection and try again.") from exc
    root = ET.fromstring(payload)
    found = []
    seen = set()
    for item in root.findall("./channel/item"):
        title = _clean_title(item.findtext("title") or "")
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        found.append(title)
        if len(found) >= limit:
            break
    return found


def headlines(topic: str, limit: int = 5) -> tuple[list[str], str]:
    """Return headlines that match the topic, and which date window they came from."""
    need = _content_words(topic)
    for span, window in WINDOWS:
        found = _fetch(topic, window, limit=12)
        if not found:
            continue
        if need:
            found = [title for title in found if _overlaps(need, title)]
        if found:
            return found[:limit], span
    raise ValueError("No headlines matched that topic. Try a broader news topic.")


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


def _shape(text: str, limit: int) -> str:
    text = text.strip().strip('"').strip("'").strip()
    text = re.sub(
        r"^(?:here(?:'s| is)(?: the| a)?(?: sentence| line| script)?|(?:sentence|line|script))\s*[:\-]\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip()
    if limit <= 20:
        match = re.match(r"(.+?[.!?])(?:\s|$)", text)
        if match and len(_words(match.group(1))) >= 8:
            text = match.group(1).strip()
    else:
        parts = re.findall(r"[^.!?]+[.!?]", text)
        if parts:
            kept = []
            count = 0
            for part in parts:
                count += len(_words(part))
                kept.append(part.strip())
                if len(kept) == 2 or count >= limit:
                    break
            text = " ".join(kept)
    if text and text[-1] not in ".!?":
        text = text.rstrip(",;:") + "."
    return text


def _ask_line(topic: str, source: str, fill: int, limit: int) -> str:
    if limit <= 20:
        shape = f"Write one spoken sentence a presenter can say on camera about that topic. Use {fill} to {limit} words."
    else:
        shape = (
            f"Write a spoken script a presenter can say on camera about that topic. "
            f"Use {fill} to {limit} words, in one or two sentences."
        )
    return (
        f"The topic is: {topic}\n"
        f"{shape} Use only facts from the headlines below. "
        "Ignore a headline that is not about the topic. "
        "Do not name a newspaper or website. "
        "Output the words only.\n\n"
        + source
    )


def _fit(text: str, topic: str, source: str, fill: int, limit: int) -> str:
    text = _shape(text, limit)
    if len(_words(text)) > limit:
        if limit <= 20:
            rewrite = f"Rewrite this as one spoken sentence of {fill} to {limit} words about that topic."
        else:
            rewrite = f"Rewrite this as one or two spoken sentences of {fill} to {limit} words about that topic."
        text = _shape(
            _ask(
                f"The topic is: {topic}\n"
                f"{rewrite} Keep only facts from the headlines. "
                "Do not name a newspaper or website. Output the words only.\n\n"
                f"Headlines:\n{source}\n\nDraft:\n{text}"
            ),
            limit,
        )
    words = _words(text)
    if len(words) > limit:
        text = " ".join(words[:limit]).rstrip(",;:") + "."
    return text


def spoken_line(topic: str, seconds: int = 5) -> dict:
    cleaned = re.sub(r"\s+", " ", topic).strip()
    if len(cleaned) < 3 or len(cleaned) > 160:
        raise ValueError("Type a short topic, such as news in ukraine war today.")
    fill, limit = script_budget(seconds)
    found, span = headlines(cleaned)
    source = "\n".join(f"- {title}" for title in found)
    text = _fit(_ask(_ask_line(cleaned, source, fill, limit)), cleaned, source, fill, limit)
    need = _content_words(cleaned)
    if need and text and not _overlaps(need, text):
        text = _fit(
            _ask(
                f"The topic is: {cleaned}\n"
                + (
                    f"The words must be about that topic. Write one spoken sentence of {fill} to {limit} words."
                    if limit <= 20
                    else f"The words must be about that topic. Write one or two spoken sentences of {fill} to {limit} words."
                )
                + " Use only the headlines below. Output the words only.\n\n"
                + source
            ),
            cleaned,
            source,
            fill,
            limit,
        )
    if not text:
        raise RuntimeError("The local model returned an empty line.")
    return {
        "script": text,
        "headlines": found,
        "model": MODEL,
        "span": span,
        "seconds": seconds,
        "words": limit,
        "fill": fill,
    }
