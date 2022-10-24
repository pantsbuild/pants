# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import tokenize
from dataclasses import dataclass
from io import BytesIO

from pants.engine.internals.parser import ParseError


@dataclass(frozen=True)
class FixBUILDFileRequest:
    path: str
    content: bytes

    @property
    def lines(self) -> list[str]:
        return self.content.decode("utf-8").splitlines(keepends=True)

    def tokenize(self) -> list[tokenize.TokenInfo]:
        try:
            return list(tokenize.tokenize(BytesIO(self.content).readline))
        except tokenize.TokenError as e:
            raise ParseError(f"Failed to parse {self.path}: {e}")


@dataclass(frozen=True)
class FixedBUILDFile:
    path: str
    content: bytes
