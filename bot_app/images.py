from __future__ import annotations

import logging
import mimetypes
import random
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import requests


LOGGER = logging.getLogger(__name__)
MEDIA_NAMESPACE = {"media": "http://search.yahoo.com/mrss/"}


@dataclass(frozen=True)
class DownloadedImage:
    content: bytes
    filename: str
    source: str
    mime_type: str


class ImageService:
    def __init__(
        self,
        source_order: tuple[str, ...],
        pinterest_rss_url: str,
        pinterest_board_url: str,
        pinterest_feed_limit: int,
        wikimedia_api_url: str,
        wikimedia_search_terms: str,
        wikimedia_result_limit: int,
        url_template: str,
        tags: str,
        width: int,
        height: int,
        timeout_seconds: float = 20,
    ) -> None:
        self.source_order = source_order
        self.pinterest_rss_url = pinterest_rss_url.strip()
        self.pinterest_board_url = pinterest_board_url.strip()
        self.pinterest_feed_limit = pinterest_feed_limit
        self.wikimedia_api_url = wikimedia_api_url.strip()
        self.wikimedia_search_terms = wikimedia_search_terms.strip()
        self.wikimedia_result_limit = wikimedia_result_limit
        self.url_template = url_template.strip()
        self.tags = tags.strip()
        self.width = width
        self.height = height
        self.timeout_seconds = timeout_seconds
        self.user_agent = "telegram-stoic-bot/1.0"

    def random_image(self) -> DownloadedImage | None:
        for source_name in self.source_order:
            try:
                image = self._image_from_source(source_name)
            except Exception as exc:
                LOGGER.warning("Image source %s failed: %s", source_name, exc)
                continue
            if image is not None:
                LOGGER.info("Selected image from %s", image.source)
                return image

        LOGGER.warning("All image sources failed; message will be delivered without an image.")
        return None

    def _image_from_source(self, source_name: str) -> DownloadedImage | None:
        if source_name == "pinterest":
            return self._try_pinterest_image()
        if source_name == "wikimedia":
            return self._try_wikimedia_image()
        if source_name == "loremflickr":
            return self._try_loremflickr_image()
        LOGGER.warning("Unsupported image source configured: %s", source_name)
        return None

    def _try_pinterest_image(self) -> DownloadedImage | None:
        feed_url = self._pinterest_feed_url()
        if not feed_url:
            LOGGER.info("Pinterest source skipped because no feed or board URL is configured.")
            return None

        response = requests.get(
            feed_url,
            headers={"User-Agent": self.user_agent, "Accept": "application/rss+xml, application/xml, text/xml"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        root = ElementTree.fromstring(response.content)
        candidates: list[str] = []
        for item in root.findall(".//item")[: self.pinterest_feed_limit]:
            candidates.extend(self._extract_pinterest_urls_from_item(item))

        return self._download_random_candidate(candidates, source_name="pinterest")

    def _extract_pinterest_urls_from_item(self, item: ElementTree.Element) -> list[str]:
        candidates: list[str] = []

        enclosure = item.find("enclosure")
        if enclosure is not None:
            enclosure_url = enclosure.get("url")
            if enclosure_url:
                candidates.append(enclosure_url.strip())

        for media_content in item.findall("media:content", MEDIA_NAMESPACE):
            url = media_content.get("url")
            if url:
                candidates.append(url.strip())

        for media_thumbnail in item.findall("media:thumbnail", MEDIA_NAMESPACE):
            url = media_thumbnail.get("url")
            if url:
                candidates.append(url.strip())

        description = item.findtext("description") or ""
        candidates.extend(re.findall(r"https://i\.pinimg\.com[^\s\"'<>]+", description))

        return self._unique_urls(candidates)

    def _pinterest_feed_url(self) -> str:
        if self.pinterest_rss_url:
            return self.pinterest_rss_url
        if not self.pinterest_board_url:
            return ""

        normalized = self.pinterest_board_url.rstrip("/")
        if normalized.endswith(".rss"):
            return normalized
        return f"{normalized}.rss"

    def _try_wikimedia_image(self) -> DownloadedImage | None:
        search_terms = [term.strip() for term in self.wikimedia_search_terms.split("|") if term.strip()]
        if not search_terms:
            LOGGER.info("Wikimedia source skipped because no search terms are configured.")
            return None

        search_term = random.choice(search_terms)
        response = requests.get(
            self.wikimedia_api_url,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": search_term,
                "gsrnamespace": 6,
                "gsrlimit": self.wikimedia_result_limit,
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "iiurlwidth": self.width,
            },
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        payload = response.json()
        pages = payload.get("query", {}).get("pages", {})
        candidates: list[str] = []
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            imageinfo = page.get("imageinfo")
            if not isinstance(imageinfo, list) or not imageinfo:
                continue
            image_data = imageinfo[0]
            if not isinstance(image_data, dict):
                continue
            mime_type = image_data.get("mime", "")
            if isinstance(mime_type, str) and not mime_type.startswith("image/"):
                continue
            url = image_data.get("thumburl") or image_data.get("url")
            if isinstance(url, str) and url.strip():
                candidates.append(url.strip())

        return self._download_random_candidate(candidates, source_name="wikimedia")

    def _try_loremflickr_image(self) -> DownloadedImage | None:
        if not self.url_template:
            LOGGER.info("loremflickr source skipped because IMAGE_API_URL_TEMPLATE is empty.")
            return None
        return self._download_image(self._random_loremflickr_url(), source_name="loremflickr")

    def _random_loremflickr_url(self) -> str:
        seed = random.randint(1000, 999999999)
        tag_groups = [tag.strip() for tag in self.tags.split("|") if tag.strip()]
        selected_tags = random.choice(tag_groups) if tag_groups else self.tags
        safe_tags = quote(selected_tags, safe=",/")
        return self.url_template.format(
            width=self.width,
            height=self.height,
            tags=safe_tags,
            seed=seed,
        )

    def _download_random_candidate(self, candidates: list[str], source_name: str) -> DownloadedImage | None:
        unique_candidates = self._unique_urls(candidates)
        if not unique_candidates:
            LOGGER.info("Image source %s returned no usable image URLs.", source_name)
            return None

        for candidate_url in random.sample(unique_candidates, k=len(unique_candidates)):
            image = self._download_image(candidate_url, source_name=source_name)
            if image is not None:
                return image
        return None

    def _download_image(self, image_url: str, source_name: str) -> DownloadedImage | None:
        response = requests.get(
            image_url,
            headers={"User-Agent": self.user_agent, "Accept": "image/*,*/*;q=0.8"},
            timeout=self.timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            LOGGER.warning("Skipping non-image response from %s: %s", source_name, content_type)
            return None

        content = response.content
        if not content:
            LOGGER.warning("Skipping empty image response from %s", source_name)
            return None

        mime_type = content_type or "image/jpeg"
        filename = self._build_filename(image_url, mime_type, source_name)
        return DownloadedImage(
            content=content,
            filename=filename,
            source=source_name,
            mime_type=mime_type,
        )

    def _build_filename(self, image_url: str, mime_type: str, source_name: str) -> str:
        parsed_url = urlparse(image_url)
        suffix = Path(parsed_url.path).suffix
        if not suffix:
            suffix = mimetypes.guess_extension(mime_type, strict=False) or ".jpg"
        return f"{source_name}{suffix}"

    @staticmethod
    def _unique_urls(urls: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for url in urls:
            cleaned = url.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique.append(cleaned)
        return unique
