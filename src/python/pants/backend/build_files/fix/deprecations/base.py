# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import tokenize
from dataclasses import dataclass
from io import BytesIO

from pants.engine.fs import FileContent
from pants.engine.internals.parser import ParseError


@dataclass(frozen=True)
class FixBUILDRequest:
    content: FileContent

    @property
    def lines(self) -> list[str]:
        return self.content.content.decode("utf-8").splitlines(keepends=True)

    def tokenize(self) -> list[tokenize.TokenInfo]:
        try:
            return list(tokenize.tokenize(BytesIO(self.content.content).readline))
        except tokenize.TokenError as e:
            raise ParseError(f"Failed to parse {self.content.path}: {e}")
