from __future__ import annotations

import random
from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class ImageService:
    url_template: str
    tags: str
    width: int
    height: int

    def random_image_url(self) -> str:
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
