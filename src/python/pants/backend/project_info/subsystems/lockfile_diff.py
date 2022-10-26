# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.generate_lockfiles import (
    GenerateToolLockfileSentinel,
    LockfileGenerated,
    LockfileGeneratedPostProcessing,
)
from pants.engine.process import InteractiveProcess, Process
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.docutil import git_url


class LockfileDiffSubsystem(PythonToolBase):
    options_scope = "lockfile-diff"
    name = "lockfile-diff"
    help = "The utility for diff-ing lockfiles."

    default_version = "lockfile-diff>=0.2.0,<0.3.0"
    default_main = ConsoleScript("lockfile-diff")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.8,<3.10"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.project_info.subsystems", "lockfile_diff.lock")
    default_lockfile_path = "src/python/pants/backend/project_info/subsystems/lockfile_diff.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("generate-lockfiles")
    args = ArgsListOption(example="--unchanged")


class LockfileDiffLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = LockfileDiffSubsystem.options_scope


class LockfileDiffPostProcessing(LockfileGenerated):
    pass


@rule
def setup_lockfile_diff_lockfile(
    _: LockfileDiffLockfileSentinel, lockfile_diff: LockfileDiffSubsystem
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(lockfile_diff)


@rule
async def lockfile_diff_post_processing(
    generated: LockfileDiffPostProcessing, lockfile_diff: LockfileDiffSubsystem
) -> LockfileGeneratedPostProcessing:
    if lockfile_diff.skip:
        return LockfileGeneratedPostProcessing()

    pex = await Get(VenvPex, PexRequest, lockfile_diff.to_pex_request())
    process = await Get(
        Process,
        VenvPexProcess(
            pex,
            argv=(
                "--new",
                generated.result.path,
                "--compare=HEAD",
                *lockfile_diff.args,
            ),
            description=f"{generated.result.resolve_name}: diff {generated.result.path}",
        ),
    )
    return LockfileGeneratedPostProcessing(
        InteractiveProcess(
            argv=(f"{{chroot}}/{process.argv[0]}", *process.argv[1:]),
            env=process.env,
            input_digest=process.input_digest,
            append_only_caches=process.append_only_caches,
            immutable_input_digests=process.immutable_input_digests,
            run_in_workspace=True,
        )
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        *pex.rules(),
        UnionRule(GenerateToolLockfileSentinel, LockfileDiffLockfileSentinel),
        UnionRule(LockfileGenerated, LockfileDiffPostProcessing),
    )
