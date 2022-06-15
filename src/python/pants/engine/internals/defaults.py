# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Tuple, Union

from pants.engine.target import Target
from pants.util.frozendict import FrozenDict

DefaultFieldValuesT = Mapping[str, Any]
DefaultsValueT = Mapping[str, DefaultFieldValuesT]
DefaultsKeyT = Union[Target, str, Tuple[Union[Target, str], ...]]
DefaultsT = Mapping[DefaultsKeyT, DefaultsValueT]


@dataclass
class BuildFileDefaultsProvider:
    # The defaults for each target from all BUILD files, per rel path.
    defaults: dict[str, dict[str, DefaultsValueT]] = field(default_factory=dict)

    def get_defaults_for(self, rel_path: str) -> dict[str, DefaultsValueT]:
        # The BUILD file parsing is executed in order to ensure we don't get a race condition
        # creating defaults here.

        if rel_path in ("/", ""):
            return self.defaults.setdefault("", {})

        parent = os.path.dirname(rel_path)
        return self.defaults.setdefault(rel_path, self.get_defaults_for(parent))

    def update_defaults_for(self, rel_path: str, defaults: Mapping[str, DefaultsValueT]) -> None:
        self.get_defaults_for(rel_path).update(defaults)


@dataclass(frozen=True)
class BuildFileDefaults:
    defaults: FrozenDict[str, DefaultsValueT]
    provider: BuildFileDefaultsProvider = field(hash=False, compare=False)

    @classmethod
    def for_path(
        cls, rel_path: str, defaults_provider: BuildFileDefaultsProvider
    ) -> BuildFileDefaults:
        return cls(
            defaults=FrozenDict(defaults_provider.get_defaults_for(rel_path)),
            provider=defaults_provider,
        )

    @staticmethod
    def update(
        defaults: dict[str, Any], target_type_aliases: Iterable[str], args: Iterable[DefaultsT]
    ) -> None:
        pass
