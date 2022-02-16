# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

from typing_extensions import final

from pants.build_graph.address import Address


@final
class TargetAdaptor:
    """A light-weight object to store target information before being converted into the Target API.

    Note that the `name` may include parametrization, e.g. `tgt@k=v`. It is not strictly equal to
    `Address.target_name`.
    """

    def __init__(self, type_alias: str, name: str, **kwargs: Any) -> None:
        self.type_alias = type_alias
        self.name = name
        self.kwargs = kwargs

    def __repr__(self) -> str:
        return f"TargetAdaptor(type_alias={self.type_alias}, name={self.name})"

    def __eq__(self, other: Any | TargetAdaptor) -> bool:
        if not isinstance(other, TargetAdaptor):
            return NotImplemented
        return (
            self.type_alias == other.type_alias
            and self.name == other.name
            and self.kwargs == other.kwargs
        )

    def to_address(self, spec_path: str) -> Address:
        parameters = {}
        if "@" in self.name:
            tgt, params_str = self.name.split("@")

            for kv in params_str.split(","):
                k, v = kv.split("=", 1)
                parameters[k] = v
        else:
            tgt = self.name

        # Because a `TargetAdaptor` cannot represent a generated target, we don't need to worry
        # about those parts of the address.
        return Address(spec_path, target_name=tgt, parameters=parameters)
