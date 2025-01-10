# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.framework.stevedore.target_types import (
    StevedoreExtensionTargets,
    StevedoreNamespacesField,
    StevedoreNamespacesProviderTargetsRequest,
)
from pants.backend.python.goals.pytest_runner import PytestPluginSetup, PytestPluginSetupRequest
from pants.backend.python.target_types import PythonDistribution
from pants.backend.python.util_rules.entry_points import (
    EntryPointsTxt,
    GenerateEntryPointsTxtRequest,
)
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class GenerateEntryPointsTxtFromStevedoreExtensionRequest(PytestPluginSetupRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        # select python_tests targets with stevedore_namespaces field
        return (
            target.has_field(StevedoreNamespacesField)
            and target.get(StevedoreNamespacesField).value is not None
        )


@rule(
    desc=f"Generate entry_points.txt to imitate `{PythonDistribution.alias}` installation.",
    level=LogLevel.DEBUG,
)
async def generate_entry_points_txt_from_stevedore_extension(
    request: GenerateEntryPointsTxtFromStevedoreExtensionRequest,
) -> PytestPluginSetup:
    requested_namespaces = request.target[StevedoreNamespacesField]
    if not requested_namespaces.value:
        return PytestPluginSetup(EMPTY_DIGEST)

    stevedore_targets = await Get(
        StevedoreExtensionTargets,
        StevedoreNamespacesProviderTargetsRequest(requested_namespaces),
    )

    requested_namespaces_value = requested_namespaces.value
    entry_points_txt = await Get(
        EntryPointsTxt,
        GenerateEntryPointsTxtRequest(
            stevedore_targets,
            lambda tgt, ns: ns in requested_namespaces_value,
            lambda tgt, ns, ep_name: True,
        ),
    )
    return PytestPluginSetup(entry_points_txt.digest)


def rules():
    return [
        *collect_rules(),
        UnionRule(
            PytestPluginSetupRequest,
            GenerateEntryPointsTxtFromStevedoreExtensionRequest,
        ),
    ]
