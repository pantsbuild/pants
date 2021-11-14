# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

from typing import Iterable

from pants.engine.target import InvalidFieldException
from pants.backend.python.macros.caof_utils import (
    OVERRIDES_TYPE,
)

class PexBinariesFromSourcesCAOF:
    """Translates N sources to equivalent `pex_binary` targets with entry_point set to the source."""

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(
        self,
        *,
        sources: str = Iterable[str],
        overrides: OVERRIDES_TYPE = None,
    ) -> None:
        overrides = overrides.copy() or {}
        for source in sources:
            values = overrides.pop(source, {})
            values.setdefault("name", os.path.splitext(source)[0])
            values.setdefault("entry_point", source)
            self._parse_context.create_object("pex_binary", **values)

        if overrides:
            raise InvalidFieldException(
                "overrides field contained one or more keys that aren't in `sources`. "
                f" Invalid keys were: '{', '.join(sorted(overrides))}'"
            )
