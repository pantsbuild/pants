# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import SourceBlock as SourceBlock  # noqa: F401
from pants.engine.internals.native_engine import TargetAdaptor as TargetAdaptor  # noqa: F401
from pants.util.ordered_set import FrozenOrderedSet


class SourceBlocks(FrozenOrderedSet[SourceBlock]):
    pass


@dataclass(frozen=True)
class TargetAdaptorRequest(EngineAwareParameter):
    """Lookup the TargetAdaptor for an Address."""

    address: Address
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

    def debug_hint(self) -> str:
        return self.address.spec
