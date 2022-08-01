from __future__ import annotations

from typing import Iterable

from experimental.metalint import metalint
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (*metalint.rules(),)
