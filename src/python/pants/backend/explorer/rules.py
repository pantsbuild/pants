# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.project_info.peek import TargetDatas
from pants.engine.rules import QueryRule
from pants.engine.target import AllTargets, AllUnexpandedTargets, UnexpandedTargets, Targets
from pants.base.specs import Specs


def rules():
    return (
        QueryRule(AllTargets, ()),
        QueryRule(AllUnexpandedTargets, ()),
        QueryRule(TargetDatas, (UnexpandedTargets,)),
        QueryRule(Targets, (Specs,)),
    )
