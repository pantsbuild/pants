# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.util.frozendict import FrozenDict
from pants.util.hash import get_hash


def test_hash() -> None:
    @dataclass(frozen=True)
    class Data:
        mapping: FrozenDict[str, str]

    data = Data(
        FrozenDict(
            {alpha: alpha.lower() for alpha in [chr(a) for a in range(ord("A"), ord("Z") + 1)]}
        )
    )
    assert (
        get_hash(data).hexdigest()
        == "e4da3c55de6ce98ddcbd5b854ff01f5c8b47fdcb2e10ddd5176505e39a332730"
    )
