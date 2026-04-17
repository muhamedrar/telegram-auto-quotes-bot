from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
STATE_FILE = DATA_DIR / "runtime_state.json"


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    partner_chat_ids: tuple[int, ...]
    admin_chat_id: int
    telegram_http_version: str
    telegram_force_ipv4: bool
    telegram_connect_timeout: float
    telegram_read_timeout: float
    auto_mode: bool
    interval_days: int
    sends_per_day: int
    random_time_mode: bool
    send_time: str
    timezone_name: str
    quote_provider: str
    quote_theme: str
    quote_api_url: str
    cohere_api_key: str
    cohere_model: str
    cohere_api_url: str
    message_tone_tags: str
    images_enabled: bool
    image_source_order: tuple[str, ...]
    pinterest_rss_url: str
    pinterest_board_url: str
    pinterest_feed_limit: int
    wikimedia_api_url: str
    wikimedia_search_terms: str
    wikimedia_result_limit: int
    image_api_url_template: str
    image_tags: str
    image_width: int
    image_height: int
    image_request_timeout: float
    log_level: str

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def load_settings() -> Settings:
    load_dotenv()

    token = _require("TELEGRAM_BOT_TOKEN")
    partner_chat_ids = _load_target_chat_ids()
    admin_chat_id_raw = (os.getenv("ADMIN_CHAT_ID") or "").strip()
    admin_chat_id = int(admin_chat_id_raw) if admin_chat_id_raw else partner_chat_ids[0]
    interval_days = max(1, int(os.getenv("INTERVAL_DAYS", "2")))
    sends_per_day = max(1, min(24, int(os.getenv("SENDS_PER_DAY", "1"))))
    send_time = os.getenv("SEND_TIME", "20:00")

    return Settings(
        telegram_bot_token=token,
        partner_chat_ids=partner_chat_ids,
        admin_chat_id=admin_chat_id,
        telegram_http_version=os.getenv("TELEGRAM_HTTP_VERSION", "1.1"),
        telegram_force_ipv4=os.getenv("TELEGRAM_FORCE_IPV4", "true").lower() == "true",
        telegram_connect_timeout=float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "20")),
        telegram_read_timeout=float(os.getenv("TELEGRAM_READ_TIMEOUT", "30")),
        auto_mode=os.getenv("AUTO_MODE", "true").lower() == "true",
        interval_days=interval_days,
        sends_per_day=sends_per_day,
        random_time_mode=os.getenv("RANDOM_TIME_MODE", "false").lower() == "true",
        send_time=send_time,
        timezone_name=os.getenv("APP_TIMEZONE", "Africa/Cairo"),
        quote_provider=os.getenv("QUOTE_PROVIDER", "cohere").strip().lower(),
        quote_theme=os.getenv("QUOTE_THEME", "stoicism, discipline, resilience, self-control, inner peace").strip(),
        quote_api_url=os.getenv("QUOTE_API_URL", "https://www.affirmations.dev/"),
        cohere_api_key=(os.getenv("COHERE_API_KEY") or "").strip(),
        cohere_model=os.getenv("COHERE_MODEL", "command-r-08-2024").strip(),
        cohere_api_url=os.getenv("COHERE_API_URL", "https://api.cohere.com/v2/chat").strip(),
        message_tone_tags=os.getenv("MESSAGE_TONE_TAGS", "romantic,gentle,encouraging"),
        images_enabled=os.getenv("IMAGES_ENABLED", "true").lower() == "true",
        image_source_order=_load_image_source_order(),
        pinterest_rss_url=os.getenv("PINTEREST_RSS_URL", "").strip(),
        pinterest_board_url=os.getenv("PINTEREST_BOARD_URL", "").strip(),
        pinterest_feed_limit=max(1, min(50, int(os.getenv("PINTEREST_FEED_LIMIT", "20")))),
        wikimedia_api_url=os.getenv(
            "WIKIMEDIA_API_URL",
            "https://commons.wikimedia.org/w/api.php",
        ).strip(),
        wikimedia_search_terms=os.getenv(
            "WIKIMEDIA_SEARCH_TERMS",
            (
                "stoic philosopher statue|marcus aurelius bust|ancient greek sculpture|"
                "roman marble bust|classical statue monochrome"
            ),
        ).strip(),
        wikimedia_result_limit=max(1, min(20, int(os.getenv("WIKIMEDIA_RESULT_LIMIT", "8")))),
        image_api_url_template=os.getenv(
            "IMAGE_API_URL_TEMPLATE",
            "https://loremflickr.com/{width}/{height}/{tags}?lock={seed}",
        ),
        image_tags=os.getenv(
            "IMAGE_TAGS",
            "flowers,roses,petals/all|sunset,sky,clouds/all|ocean,beach,waves/all|forest,mountains,nature/all",
        ),
        image_width=max(400, int(os.getenv("IMAGE_WIDTH", "1200"))),
        image_height=max(400, int(os.getenv("IMAGE_HEIGHT", "1600"))),
        image_request_timeout=float(os.getenv("IMAGE_REQUEST_TIMEOUT", "20")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        level=getattr(logging, level, logging.INFO),
    )


def ensure_directories() -> None:
    DATA_DIR.mkdir(exist_ok=True)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_target_chat_ids() -> tuple[int, ...]:
    raw_chat_ids = (os.getenv("TELEGRAM_CHAT_IDS") or "").strip()
    if not raw_chat_ids:
        return (int(_require("TELEGRAM_CHAT_ID")),)

    chat_ids: list[int] = []
    for raw_value in raw_chat_ids.split(","):
        value = raw_value.strip()
        if not value:
            continue
        chat_ids.append(int(value))

    if not chat_ids:
        raise RuntimeError("TELEGRAM_CHAT_IDS must contain at least one numeric chat ID.")
    return tuple(chat_ids)


def _load_image_source_order() -> tuple[str, ...]:
    supported_sources = {"pinterest", "wikimedia", "loremflickr"}
    raw_value = os.getenv("IMAGE_SOURCE_ORDER", "pinterest,wikimedia,loremflickr")
    parsed_sources: list[str] = []

    for raw_source in raw_value.split(","):
        source = raw_source.strip().lower()
        if not source or source not in supported_sources or source in parsed_sources:
            continue
        parsed_sources.append(source)

    if not parsed_sources:
        return ("wikimedia", "loremflickr")
    return tuple(parsed_sources)
