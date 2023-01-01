# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import ClassVar

from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.lifecycle import (
    BuildServerCapabilities,
    CompileProvider,
    DebugProvider,
    InitializeBuildParams,
    InitializeBuildResult,
    RunProvider,
    TestProvider,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.version import VERSION

# Version of BSP supported by Pants.
BSP_VERSION = "2.0.0"


@union
class BSPLanguageSupport:
    """Union exposed by language backends to inform BSP core rules of capabilities to advertise to
    clients."""

    language_id: ClassVar[str]
    can_compile: bool = False
    can_test: bool = False
    can_run: bool = False
    can_debug: bool = False
    can_provide_resources: bool = False


# -----------------------------------------------------------------------------------------------
# Initialize Build Request
# See https://build-server-protocol.github.io/docs/specification.html#initialize-build-request
# -----------------------------------------------------------------------------------------------


class InitializeBuildHandlerMapping(BSPHandlerMapping):
    method_name = "build/initialize"
    request_type = InitializeBuildParams
    response_type = InitializeBuildResult


@rule
async def bsp_build_initialize(
    _request: InitializeBuildParams, union_membership: UnionMembership
) -> InitializeBuildResult:
    compile_provider_language_ids = []
    test_provider_language_ids = []
    run_provider_language_ids = []
    debug_provider_language_ids = []
    resources_provider = False
    language_support_impls = union_membership.get(BSPLanguageSupport)
    for lang in language_support_impls:
        if lang.can_compile:
            compile_provider_language_ids.append(lang.language_id)
        if lang.can_test:
            test_provider_language_ids.append(lang.language_id)
        if lang.can_run:
            run_provider_language_ids.append(lang.language_id)
        if lang.can_debug:
            debug_provider_language_ids.append(lang.language_id)
        if lang.can_provide_resources:
            resources_provider = True

    return InitializeBuildResult(
        display_name="Pants",
        version=VERSION,
        bsp_version=BSP_VERSION,  # TODO: replace with an actual BSP version
        capabilities=BuildServerCapabilities(
            compile_provider=CompileProvider(
                language_ids=tuple(sorted(compile_provider_language_ids))
            ),
            test_provider=TestProvider(language_ids=tuple(sorted(test_provider_language_ids))),
            run_provider=RunProvider(language_ids=tuple(sorted(run_provider_language_ids))),
            debug_provider=DebugProvider(language_ids=tuple(sorted(debug_provider_language_ids))),
            inverse_sources_provider=None,
            dependency_sources_provider=True,
            dependency_modules_provider=True,
            resources_provider=resources_provider,
            can_reload=None,
            build_target_changed_provider=None,
        ),
        data=None,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPHandlerMapping, InitializeBuildHandlerMapping),
    )
