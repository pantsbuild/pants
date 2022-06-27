# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.goals.run_helper import _create_python_source_run_request
from pants.backend.python.target_types import PexBinaryDefaults
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PexRuntimeEnvironment
from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@rule(level=LogLevel.DEBUG)
async def create_pex_binary_run_request(
    field_set: PexBinaryFieldSet,
    pex: PexRuntimeEnvironment,
    pex_binary_defaults: PexBinaryDefaults,
    pex_env: PexEnvironment,
) -> RunRequest:
    if pex.run_packaged_firstparty:
        built_pex = await Get(BuiltPackage, PexBinaryFieldSet, field_set)
        relpath = built_pex.artifacts[0].relpath
        assert relpath is not None
        return RunRequest(
            digest=built_pex.digest,
            args=[os.path.join("{chroot}", relpath)],
        )

    return await _create_python_source_run_request(
        field_set.address,
        entry_point_field=field_set.entry_point,
        pex_env=pex_env,
        run_in_sandbox=field_set.run_in_sandbox.value,
        console_script=field_set.script.value,
        additional_pex_args=field_set.generate_additional_args(pex_binary_defaults),
    )


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, PexBinaryFieldSet)]
