# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar, Iterable, Optional

from pants.engine.internals.native_engine import Address
from pants.engine.target import DictStringToStringField, InvalidFieldException
from pants.util.frozendict import FrozenDict


# TODO: dependency inference based on script_src (values of this dict)
class NfpmPackageScriptsField(DictStringToStringField):
    nfpm_alias = ""  # maps to more than one nfpm.yaml field
    alias: ClassVar[str] = "scripts"
    # The keys of nfpm_aliases are the only valid keys of this field.
    nfpm_aliases: ClassVar[FrozenDict[str, str]] = FrozenDict(
        {
            # The general scripts common to all packager types
            "preinstall": "scripts.preinstall",
            "postinstall": "scripts.postinstall",
            "preremove": "scripts.preremove",
            "postremove": "scripts.postremove",
        }
    )

    @classmethod
    def compute_value(
        cls, raw_value: Optional[dict[str, Iterable[str]]], address: Address
    ) -> Optional[FrozenDict[str, tuple[str, ...]]]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default:
            invalid_keys = value_or_default.keys() - cls.nfpm_aliases.keys()
            if invalid_keys:
                raise InvalidFieldException(
                    f"Each key for the '{cls.alias}' field in target {address} must be one of"
                    f"{repr(tuple(cls.nfpm_aliases.keys()))}, but {repr(invalid_keys)} was provided.",
                )
        return value_or_default
