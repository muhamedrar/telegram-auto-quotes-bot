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


FALLBACK_QUOTES = [
    Quote("Discipline is the quiet strength that keeps the soul from drifting."),
    Quote("Master your mind, and the world loses much of its power over you."),
    Quote("A calm heart turns hardship into practice."),
    Quote("What you endure with order becomes part of your strength."),
    Quote("Control your response, and fate loses its sharpest weapon."),
    Quote("The strongest person is often the one who stays composed."),
    Quote("Let your principles speak louder than your moods."),
    Quote("Endure the moment well, and the next one becomes lighter."),
    Quote("Peace begins when you stop arguing with what you cannot control."),
    Quote("Train your thoughts, and your days will obey your character."),
    Quote("A steady mind can walk through chaos without borrowing its noise."),
    Quote("Restraint is not weakness; it is power under command."),
    Quote("The obstacle is often the place where character gets forged."),
    Quote("Carry yourself with order, even when the world does not."),
    Quote("The soul grows stronger each time it chooses reason over panic."),
    Quote("Stand firm, speak less, and let your actions reveal your discipline."),
    Quote("Hardship is lighter when the mind refuses to kneel before it."),
    Quote("Patience is strength that has learned how to breathe."),
    Quote("The wise person does not chase peace; they practice it."),
    Quote("Self-control turns pressure into dignity."),
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
        "stoic",
        "disciplined",
        "resilient",
        "philosophical",
        "minimal",
        "intense",
    }
    TONE_ALIASES = {
        "lovely": "sweet",
        "soft": "gentle",
        "warm": "cozy",
        "comforting": "reassuring",
        "cute": "playful",
        "caring": "supportive",
        "stoicism": "stoic",
        "discipline": "disciplined",
        "badass": "intense",
    }

    def __init__(
        self,
        provider: str,
        api_url: str,
        tone_tags: str = "",
        quote_theme: str = "stoicism, discipline, resilience, self-control, inner peace",
        cohere_api_key: str = "",
        cohere_model: str = "command-r-08-2024",
        cohere_api_url: str = "https://api.cohere.com/v2/chat",
        timeout_seconds: int = 15,
    ) -> None:
        self.provider = provider.strip().lower() or "cohere"
        self.api_url = api_url.strip()
        self.tone_tags = self._parse_tone_tags(tone_tags)
        self.quote_theme = quote_theme.strip() or "stoicism, discipline, resilience, self-control, inner peace"
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

        LOGGER.info("Selecting a built-in fallback quote")
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
                "temperature": 0.85,
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
        tone_hint = ", ".join(self.tone_tags) if self.tone_tags else "stoic, calm, disciplined"
        avoid_text = (
            f" Avoid reusing or closely paraphrasing this quote: {self.last_generated_text}."
            if self.last_generated_text
            else ""
        )
        return (
            "Generate a JSON object with one field named text. "
            "The text must be one original stoic quote or aphorism. "
            f"Core themes: {self.quote_theme}. "
            f"Style tags: {tone_hint}. "
            "Keep it to a single sentence, around 8 to 18 words. "
            "It should feel disciplined, calm, sharp, reflective, and memorable. "
            "Do not include quotation marks, emojis, hashtags, markdown, or an author name."
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
        choices = [quote for quote in FALLBACK_QUOTES if quote.text != self.last_generated_text]
        chosen_quote = random.choice(choices or FALLBACK_QUOTES)
        self.last_generated_text = chosen_quote.text
        return chosen_quote
