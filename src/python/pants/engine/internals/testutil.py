# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import RawSpecs, RawSpecsWithoutFileOwners, Spec
from pants.engine.addresses import Addresses
from pants.engine.internals.native_engine import Address
from pants.testutil.rule_runner import RuleRunner


def resolve_raw_specs_without_file_owners(
    rule_runner: RuleRunner,
    specs: Iterable[Spec],
    ignore_nonexistent: bool = False,
) -> list[Address]:
    specs_obj = RawSpecs.create(
        specs,
        filter_by_global_options=True,
        unmatched_glob_behavior=(
            GlobMatchErrorBehavior.ignore if ignore_nonexistent else GlobMatchErrorBehavior.error
        ),
        description_of_origin="tests",
    )
    result = rule_runner.request(Addresses, [RawSpecsWithoutFileOwners.from_raw_specs(specs_obj)])
    return sorted(result)
