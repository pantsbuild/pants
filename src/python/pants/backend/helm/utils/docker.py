# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageRef:
    registry: str | None
    repository: str
    tag: str | None

    @classmethod
    def parse(cls, image_ref: str) -> ImageRef:
        registry = None
        tag = None

        addr_and_tag = image_ref.split(":")
        if len(addr_and_tag) > 1:
            tag = addr_and_tag[1]

        slash_idx = addr_and_tag[0].find("/")
        if slash_idx >= 0:
            registry = addr_and_tag[0][:slash_idx]
            repo = addr_and_tag[0][(slash_idx + 1) :]
        else:
            repo = addr_and_tag[0]

        return cls(registry=registry, repository=repo, tag=tag)

    def __str__(self) -> str:
        result = ""
        if self.registry:
            result += f"{self.registry}/"
        result += self.repository
        if self.tag:
            result += f":{self.tag}"
        return result
