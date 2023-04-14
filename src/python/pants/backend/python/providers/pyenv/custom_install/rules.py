# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20

from pants.backend.python.providers.pyenv.custom_install.target_types import (
    PyenvInstallSentinelField,
)
from pants.backend.python.providers.pyenv.rules import (
    PyenvInstallInfoRequest,
    PyenvPythonProviderSubsystem,
)
from pants.backend.python.providers.pyenv.rules import rules as pyenv_rules
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.external_tool import rules as external_tools_rules
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.internals.synthetic_targets import SyntheticAddressMaps, SyntheticTargetsRequest
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class SyntheticPyenvTargetsRequest(SyntheticTargetsRequest):
    path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


@rule
async def make_synthetic_targets(request: SyntheticPyenvTargetsRequest) -> SyntheticAddressMaps:
    return SyntheticAddressMaps.for_targets_request(
        request,
        [
            (
                "BUILD.pyenv",
                (
                    TargetAdaptor(
                        "_pyenv_install",
                        name="pants-pyenv-install",
                        __description_of_origin__="the `pyenv` provider",
                    ),
                ),
            )
        ],
    )


@dataclass(frozen=True)
class RunPyenvInstallFieldSet(RunFieldSet):
    run_in_sandbox_behavior = RunInSandboxBehavior.NOT_SUPPORTED
    required_fields = (PyenvInstallSentinelField,)

    _sentinel: PyenvInstallSentinelField


@rule
async def run_pyenv_install(
    _: RunPyenvInstallFieldSet,
    platform: Platform,
    pyenv_subsystem: PyenvPythonProviderSubsystem,
) -> RunRequest:
    run_request, pyenv = await MultiGet(
        Get(RunRequest, PyenvInstallInfoRequest()),
        Get(DownloadedExternalTool, ExternalToolRequest, pyenv_subsystem.get_request(platform)),
    )

    wrapper_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "run_install_python_shim.sh",
                    dedent(
                        f"""\
                        #!/usr/bin/env bash
                        set -e
                        cd "$CHROOT"
                        SPECIFIC_VERSION=$("{pyenv.exe}" latest --known $1)
                        {" ".join(run_request.args)} $SPECIFIC_VERSION
                        """
                    ).encode(),
                    is_executable=True,
                )
            ]
        ),
    )
    digest = await Get(Digest, MergeDigests([run_request.digest, wrapper_script_digest]))
    return dataclasses.replace(
        run_request,
        args=("{chroot}/run_install_python_shim.sh",),
        digest=digest,
        extra_env=FrozenDict(
            {
                "CHROOT": "{chroot}",
                **run_request.extra_env,
            }
        ),
    )


def rules():
    return (
        *collect_rules(),
        *external_tools_rules(),
        *pyenv_rules(),
        *RunPyenvInstallFieldSet.rules(),
        UnionRule(SyntheticTargetsRequest, SyntheticPyenvTargetsRequest),
    )
