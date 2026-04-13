from __future__ import annotations

import json
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
    Quote("You are so deeply loved, and I hope today feels a little softer because of that."),
    Quote("No matter how heavy the day feels, I believe in your heart and your strength."),
    Quote("You make life warmer, calmer, and more beautiful just by being in it."),
    Quote("I hope you remember today that you are precious, strong, and never alone."),
    Quote("Even on your hardest days, you are still someone wonderful and deeply worthy of love."),
    Quote("You deserve gentleness, rest, and a thousand reminders of how special you are."),
    Quote("I am so proud of the way you keep going, even when things feel difficult."),
    Quote("Your smile has a way of making everything around you feel lighter and sweeter."),
    Quote("I hope this message wraps around your heart like a small warm hug."),
    Quote("You are one of the best things in this world, and I hope you never forget that."),
    Quote("You bring comfort, kindness, and light in a way that only you can."),
    Quote("If today feels tiring, please remember how loved and appreciated you are."),
    Quote("You are doing better than you think, and I am always cheering for you."),
    Quote("Your heart is beautiful, and the world is better because you are in it."),
    Quote("You deserve happy moments, peaceful thoughts, and love that feels safe."),
    Quote("Just a reminder that you matter so much, and you make my world brighter."),
    Quote("I hope today gives you a reason to smile, even if it starts with this little message."),
    Quote("You have such a gentle strength, and I admire that about you so much."),
    Quote("Whatever today looks like, I hope you feel loved, supported, and seen."),
    Quote("You are my favorite kind of peace, and I hope your heart feels calm today."),
]


class QuoteService:
    SUPPORTED_TONE_TAGS = {
        "romantic",
        "gentle",
        "encouraging",
        "supportive",
        "reassuring",
        "affectionate",
        "cozy",
        "playful",
        "proud",
        "calm",
        "sweet",
    }
    TONE_ALIASES = {
        "lovely": "sweet",
        "soft": "gentle",
        "warm": "cozy",
        "comforting": "reassuring",
        "cute": "playful",
        "caring": "supportive",
    }

    def __init__(
        self,
        provider: str,
        api_url: str,
        tone_tags: str = "",
        cohere_api_key: str = "",
        cohere_model: str = "command-r-08-2024",
        cohere_api_url: str = "https://api.cohere.com/v2/chat",
        timeout_seconds: int = 15,
    ) -> None:
        self.provider = provider.strip().lower() or "cohere"
        self.api_url = api_url.strip()
        self.tone_tags = self._parse_tone_tags(tone_tags)
        self.cohere_api_key = cohere_api_key.strip()
        self.cohere_model = cohere_model.strip() or "command-r-08-2024"
        self.cohere_api_url = cohere_api_url.strip() or "https://api.cohere.com/v2/chat"
        self.timeout_seconds = timeout_seconds
        self.last_generated_text: str | None = None

    def random_quote(self) -> Quote:
        provider = self.provider
        if provider == "cohere":
            quote = self._try_cohere_quote()
            if quote is not None:
                return quote
            quote = self._try_api_quote()
            if quote is not None:
                return quote
        elif provider == "api":
            quote = self._try_api_quote()
            if quote is not None:
                return quote
        else:
            LOGGER.warning("Unknown quote provider '%s'. Falling back to available providers.", provider)
            quote = self._try_cohere_quote() or self._try_api_quote()
            if quote is not None:
                return quote

        LOGGER.info("Selecting a built-in fallback message")
        return self._random_fallback_quote()

    def _try_cohere_quote(self) -> Quote | None:
        if not self.cohere_api_key:
            LOGGER.warning("Cohere provider is selected but COHERE_API_KEY is missing.")
            return None

        quote: Quote | None = None
        for _ in range(3):
            try:
                quote = self._generate_cohere_quote()
            except Exception as exc:
                LOGGER.warning("Cohere quote generation failed: %s", exc)
                return None
            if quote.text != self.last_generated_text:
                self.last_generated_text = quote.text
                return quote

        if quote is not None:
            self.last_generated_text = quote.text
            return quote
        return None

    def _generate_cohere_quote(self) -> Quote:
        prompt = self._build_cohere_prompt()
        response = requests.post(
            self.cohere_api_url,
            headers={
                "Authorization": f"Bearer {self.cohere_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": self.cohere_model,
                "message": prompt,
                "temperature": 0.9,
                "max_tokens": 120,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        content_text = self._extract_cohere_text(response.json())
        payload = self._load_json_from_text(content_text)
        quote_text = payload.get("text", "") if isinstance(payload, dict) else ""
        cleaned_text = self._clean_generated_text(quote_text)
        if not cleaned_text:
            raise RuntimeError("Cohere response did not include a usable quote text.")
        return Quote(text=cleaned_text)

    def _build_cohere_prompt(self) -> str:
        tone_hint = ", ".join(self.tone_tags) if self.tone_tags else "warm, encouraging"
        avoid_text = (
            f" Avoid reusing or closely paraphrasing this quote: {self.last_generated_text}."
            if self.last_generated_text
            else ""
        )
        return (
            "Generate a JSON object with one field named text. "
            "The text must be one original personalized quote for someone you care about. "
            f"Use these tone tags: {tone_hint}."
            " Keep it to a single sentence, around 8 to 18 words. "
            "Do not include quotation marks, emojis, hashtags, markdown, or an author name."
            "Do not repeat the quotes"
            f"{avoid_text}"
        )

    def _extract_cohere_text(self, payload: dict[str, Any]) -> str:
        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                text_parts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_value = item.get("text")
                        if isinstance(text_value, str):
                            text_parts.append(text_value)
                if text_parts:
                    return "\n".join(text_parts)

        text_value = payload.get("text")
        if isinstance(text_value, str):
            return text_value

        raise RuntimeError("Unexpected Cohere response shape.")

    def _load_json_from_text(self, raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            return json.loads(cleaned)

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise RuntimeError("Cohere did not return a JSON object.")
        return json.loads(match.group(0))

    def _clean_generated_text(self, text: str) -> str:
        cleaned = text.strip().strip('"').strip("'")
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s+-\s+.+$", "", cleaned)
        return cleaned.strip()

    def _try_api_quote(self) -> Quote | None:
        if not self.api_url:
            return None
        try:
            response = requests.get(self.api_url, timeout=self.timeout_seconds)
            response.raise_for_status()
            quote = self._parse_api_payload(response.json())
            if quote.text != self.last_generated_text:
                self.last_generated_text = quote.text
            return quote
        except Exception as exc:
            LOGGER.warning("Legacy quote API failed: %s", exc)
            return None

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
        return Quote(text=self._clean_generated_text(text), author=author)

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
            if normalized in cls.SUPPORTED_TONE_TAGS and normalized not in parsed:
                parsed.append(normalized)
        return parsed

    def _random_fallback_quote(self) -> Quote:
        choices = [quote for quote in LOVELY_MESSAGES if quote.text != self.last_generated_text]
        chosen_quote = random.choice(choices or LOVELY_MESSAGES)
        self.last_generated_text = chosen_quote.text
        return chosen_quote
