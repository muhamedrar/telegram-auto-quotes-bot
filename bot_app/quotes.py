from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quote:
    text: str
    author: str = ""

    @property
    def formatted(self) -> str:
        if not self.author:
            return self.text
        return f"{self.text}\n\n- {self.author}"

    @property
    def spoken_text(self) -> str:
        text = self.text
        text = text.replace(";", ",")
        text = text.replace(":", ",")
        text = text.replace("&", "and")
        text = text.replace("“", '"').replace("”", '"')
        text = text.replace("’", "'")
        text = re.sub(r"\s+", " ", text).strip()
        return text


LOVELY_MESSAGES = [
    Quote("You are so deeply loved, and I hope today feels a little softer because of that.", "Nahla Bot"),
    Quote("No matter how heavy the day feels, I believe in your heart and your strength.", "Nahla Bot"),
    Quote("You make life warmer, calmer, and more beautiful just by being in it.", "Nahla Bot"),
    Quote("I hope you remember today that you are precious, strong, and never alone.", "Nahla Bot"),
    Quote("Even on your hardest days, you are still someone wonderful and deeply worthy of love.", "Nahla Bot"),
    Quote("You deserve gentleness, rest, and a thousand reminders of how special you are.", "Nahla Bot"),
    Quote("I am so proud of the way you keep going, even when things feel difficult.", "Nahla Bot"),
    Quote("Your smile has a way of making everything around you feel lighter and sweeter.", "Nahla Bot"),
    Quote("I hope this message wraps around your heart like a small warm hug.", "Nahla Bot"),
    Quote("You are one of the best things in this world, and I hope you never forget that.", "Nahla Bot"),
    Quote("You bring comfort, kindness, and light in a way that only you can.", "Nahla Bot"),
    Quote("If today feels tiring, please remember how loved and appreciated you are.", "Nahla Bot"),
    Quote("You are doing better than you think, and I am always cheering for you.", "Nahla Bot"),
    Quote("Your heart is beautiful, and the world is better because you are in it.", "Nahla Bot"),
    Quote("You deserve happy moments, peaceful thoughts, and love that feels safe.", "Nahla Bot"),
    Quote("Just a reminder that you matter so much, and you make my world brighter.", "Nahla Bot"),
    Quote("I hope today gives you a reason to smile, even if it starts with this little message.", "Nahla Bot"),
    Quote("You have such a gentle strength, and I admire that about you so much.", "Nahla Bot"),
    Quote("Whatever today looks like, I hope you feel loved, supported, and seen.", "Nahla Bot"),
    Quote("You are my favorite kind of peace, and I hope your heart feels calm today.", "Nahla Bot"),
]


class QuoteService:
    TONE_SNIPPETS = {
        "romantic": [
            "You mean so much to me, and I hope you feel that today.",
            "My heart feels softer every time I think of you.",
        ],
        "gentle": [
            "I hope today feels a little softer around your heart.",
            "Take this as a quiet reminder that you deserve tenderness.",
        ],
        "encouraging": [
            "You are doing better than you think, and I believe in you.",
            "You have more strength in you than this day can take away.",
        ],
        "supportive": [
            "I am with you in spirit, cheering for you in every little step.",
            "Whatever today looks like, you do not have to carry it alone.",
        ],
        "reassuring": [
            "You are loved, safe in my heart, and never alone.",
            "No matter what today brings, you are deeply cared for.",
        ],
        "affectionate": [
            "Sending you a little extra love with this message.",
            "Consider this a soft little reminder of how adored you are.",
        ],
        "cozy": [
            "I hope this lands like a warm hug and a quiet exhale.",
            "Wrapping you in the coziest thoughts from afar.",
        ],
        "playful": [
            "Tiny reminder from me: you are ridiculously lovable.",
            "Just dropping by to say you are my favorite kind of wonderful.",
        ],
        "proud": [
            "I am so proud of the way you keep showing up.",
            "You deserve to feel proud of yourself too.",
        ],
        "calm": [
            "I hope a peaceful little moment finds you soon.",
            "May your heart feel lighter and calmer with every breath.",
        ],
        "sweet": [
            "You make the world feel sweeter just by being in it.",
            "I hope something lovely finds you today, starting with this.",
        ],
    }
    TONE_ALIASES = {
        "lovely": "sweet",
        "soft": "gentle",
        "warm": "cozy",
        "comforting": "reassuring",
        "cute": "playful",
        "caring": "supportive",
    }

    def __init__(self, api_url: str, tone_tags: str = "", timeout_seconds: int = 15) -> None:
        self.api_url = api_url
        self.tone_tags = self._parse_tone_tags(tone_tags)
        self.timeout_seconds = timeout_seconds

    def random_quote(self) -> Quote:
        if self.api_url:
            try:
                response = requests.get(self.api_url, timeout=self.timeout_seconds)
                response.raise_for_status()
                return self._apply_tone(self._parse_api_payload(response.json()))
            except Exception as exc:
                LOGGER.warning("Falling back to built-in lovely messages after API error: %s", exc)

        LOGGER.info("Selecting a lovely built-in message")
        return self._apply_tone(random.choice(LOVELY_MESSAGES))

    def _parse_api_payload(self, payload: Any) -> Quote:
        if isinstance(payload, list) and payload:
            payload = payload[0]

        if not isinstance(payload, dict):
            raise RuntimeError("API response was not a JSON object.")

        text = self._pick_first_text(
            payload,
            ["affirmation", "reason", "message", "text", "quote", "body"],
        )
        if not text:
            raise RuntimeError("API response did not contain a supported message field.")

        author = self._pick_first_text(payload, ["author", "source", "from", "by"]) or ""
        return Quote(text=text, author=author)

    @staticmethod
    def _pick_first_text(payload: dict[str, Any], keys: list[str]) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _parse_tone_tags(cls, tone_tags: str) -> list[str]:
        parsed: list[str] = []
        for raw_tag in tone_tags.split(","):
            tag = raw_tag.strip().lower()
            if not tag:
                continue
            normalized = cls.TONE_ALIASES.get(tag, tag)
            if normalized in cls.TONE_SNIPPETS and normalized not in parsed:
                parsed.append(normalized)
        return parsed

    def _apply_tone(self, quote: Quote) -> Quote:
        if not self.tone_tags:
            return quote

        snippet_pool: list[str] = []
        for tag in self.tone_tags:
            snippet_pool.extend(self.TONE_SNIPPETS.get(tag, []))

        if not snippet_pool:
            return quote

        chosen_snippet = random.choice(snippet_pool)
        if chosen_snippet.lower() in quote.text.lower():
            return quote

        return Quote(text=f"{quote.text}\n\n{chosen_snippet}", author=quote.author)
