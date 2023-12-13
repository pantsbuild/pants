# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any, cast

from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class TemplatedBackendConfig:
    package: str
    kwargs: FrozenDict[str, Any]

    @classmethod
    def from_dict(cls, d: Any):
        d = dict(d)
        package = d.pop("package", None)
        if not package:
            raise ValueError('"package" is a required key for a backend template')
        return cls(package=cast(str, package), kwargs=FrozenDict(d))
