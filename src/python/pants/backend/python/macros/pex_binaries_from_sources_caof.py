# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from typing import Iterable

from pants.backend.python.macros.caof_utils import OVERRIDES_TYPE, flatten_overrides
from pants.engine.target import InvalidFieldException


class PexBinariesFromSourcesCAOF:
    """Translates N sources to equivalent `pex_binary` targets with entry_point set to the
    source."""

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(
        self,
        *,
        sources: Iterable[str],
        overrides: OVERRIDES_TYPE = None,
    ) -> None:
        flattened_overrides = flatten_overrides(
            overrides,
            macro_name="pex_binaries_from_sources",
            build_file_dir=self._parse_context.rel_path,
        )
        for source in sources:
            values = flattened_overrides.pop(source, {})
            values.setdefault("name", os.path.splitext(source)[0])
            values.setdefault("entry_point", source)
            self._parse_context.create_object("pex_binary", **values)

        if flattened_overrides:
            raise InvalidFieldException(
                "overrides field contained one or more keys that aren't in `sources`. "
                f" Invalid keys were: '{', '.join(sorted(flattened_overrides.keys()))}'"
            )
