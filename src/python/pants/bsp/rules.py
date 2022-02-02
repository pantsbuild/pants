# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.bsp.spec import BuildServerCapabilities, InitializeBuildParams, InitializeBuildResult
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.version import VERSION


@rule
async def bsp_build_initialize(_request: InitializeBuildParams) -> InitializeBuildResult:
    return InitializeBuildResult(
        display_name="Pants",
        version=VERSION,
        bsp_version="0.0.1",  # TODO: replace with an actual BSP version
        capabilities=BuildServerCapabilities(
            compile_provider=None,
            test_provider=None,
            run_provider=None,
            debug_provider=None,
            inverse_sources_provider=None,
            dependency_sources_provider=None,
            dependency_modules_provider=None,
            resources_provider=None,
            can_reload=None,
            build_target_changed_provider=None,
        ),
        data=None,
    )


def rules():
    return (
        *collect_rules(),
        QueryRule(InitializeBuildResult, (InitializeBuildParams,)),
    )
