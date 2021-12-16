# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.compile import ClasspathEntryRequest, FallibleClasspathEntry
from pants.jvm.target_types import JvmResourcesFieldSet, JvmResourcesGeneratorFieldSet


class JvmResourcesRequest(ClasspathEntryRequest):
    field_sets = (
        JvmResourcesFieldSet,
        JvmResourcesGeneratorFieldSet,
    )


@rule(desc="Fetch with coursier")
async def fetch_with_coursier(request: JvmResourcesRequest) -> FallibleClasspathEntry:

    raise Exception(request)


def rules():
    return [
        *collect_rules(),
        UnionRule(ClasspathEntryRequest, JvmResourcesRequest),
    ]
