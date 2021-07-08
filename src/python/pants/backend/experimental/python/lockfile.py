# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import cast

from pants.backend.python.util_rules.pex import VenvPex, PexRequest, PexRequirements, VenvPexProcess
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.target_types import ConsoleScript, PythonRequirementsField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.engine.fs import Digest, CreateDigest, FileContent, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import ProcessResult
from pants.engine.rules import goal_rule, Get, collect_rules, MultiGet
from pants.engine.target import Targets
from pants.util.strutil import pluralize


logger = logging.getLogger(__name__)


class PipCompile(PythonToolBase):
    options_scope = "pip_compile"
    help = "Used to generate lockfiles for third-party Python dependencies."

    default_version = "pip-tools==6.2.0"
    default_main = ConsoleScript("pip-compile")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # TODO: How should users indicate where to save the lockfile to when we have per-tool
        #  lockfiles and mmultiple user lockfiles?
        register(
            "--lockfile-dest",
            type=str,
            default="3rdparty/python/lockfile.txt",
            help="The file path to be created.\n\nThis will overwrite any previous files."
        )

    @property
    def lockfile_dest(self) -> str:
        return cast(str, self.options.lockfile_dest)


class LockSubsystem(GoalSubsystem):
    name = "lock"


class LockGoal(Goal):
    subsystem_cls = LockSubsystem


# TODO: What should the input to `./pants lock` be when generating user lockfiles? Currently, it's
#  the 3rd-party requirements that get used as input. Likely it should instead be all 3rd party
#  reqs used by the transitive closure? That would better mirror generate_lockfile.sh.
@goal_rule
async def generate_lockfile(
    targets: Targets, pip_compile_subsystem: PipCompile, workspace: Workspace
) -> LockGoal:
    reqs = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        for tgt in targets
        if tgt.has_field(PythonRequirementsField)
    )

    input_requirements_get = Get(
        Digest, CreateDigest([FileContent("requirements.in", "\n".join(reqs).encode())])
    )
    pip_compile_get = Get(
        VenvPex,
        PexRequest(
            output_filename="pip_compile.pex",
            internal_only=True,
            requirements=PexRequirements(pip_compile_subsystem.all_requirements),
            # TODO: Figure out which interpreter constraints to use...Among other reasons, this is
            #  tricky because python_requirement_library targets don't have interpreter constraints!
            interpreter_constraints=InterpreterConstraints(["CPython==3.9.*"]),
            main=pip_compile_subsystem.main
        )
    )
    input_requirements, pip_compile = await MultiGet(input_requirements_get, pip_compile_get)

    dest = pip_compile_subsystem.lockfile_dest
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            pip_compile,
            description=(
                f"Generate lockfile for {pluralize(len(reqs), 'requirements')}: {', '.join(reqs)}"
            ),
            argv=[
                "requirements.in",
                "--generate-hashes",
                f"--output-file={dest}",
                # NB: This allows pinning setuptools et al, which we must do. This will become
                # the default in a future version of pip-tools.
                "--allow-unsafe",
            ],
            input_digest=input_requirements,
            output_files=(dest,),
        )
    )
    # TODO: rewrite the file to have Pants header info, like how to regenerate the lockfile w/
    #  Pants.
    workspace.write_digest(result.output_digest)
    logger.info(f"Wrote lockfile to {dest}")

    return LockGoal(exit_code=0)


def rules():
    return collect_rules()
