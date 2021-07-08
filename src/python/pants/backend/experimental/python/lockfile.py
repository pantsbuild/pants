# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class PipToolsSubsystem(PythonToolBase):
    options_scope = "pip-tools"
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
            help="The file path to be created.\n\nThis will overwrite any previous files.",
        )

    @property
    def lockfile_dest(self) -> str:
        return cast(str, self.options.lockfile_dest)


class LockSubsystem(GoalSubsystem):
    name = "lock"
    help = "Generate a lockfile."


class LockGoal(Goal):
    subsystem_cls = LockSubsystem


@goal_rule
async def generate_lockfile(
    addresses: Addresses, pip_tools_subsystem: PipToolsSubsystem, workspace: Workspace
) -> LockGoal:
    # TODO: Looking at the transitive closure to generate a single lockfile will not work when we
    #  have multiple lockfiles supported, via per-tool lockfiles and multiple user lockfiles.
    #  Ideally, `./pants lock ::` would mean "regenerate all unique lockfiles", whereas now it
    #  means "generate a single lockfile based on this transitive closure."
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    reqs = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        # NB: By looking at the dependencies, rather than the closure, we only generate for
        # requirements that are actually used in the project.
        #
        # TODO: It's not totally clear to me if that is desirable. Consider requirements like
        #  pydevd-pycharm. Should that be in the lockfile? I think this needs to be the case when
        #  we have multiple lockfiles, though: we shouldn't look at the universe in that case,
        #  only the relevant subset of requirements.
        #
        # Note that the current generate_lockfile.sh script in our docs also mixes in
        #  `requirements.txt`, but not inlined python_requirement_library targets if they're not
        #  in use. We don't have a way to emulate those semantics because at this point, all we
        #  have is `python_requirement_library` targets without knowing the source.
        for tgt in transitive_targets.dependencies
        if tgt.has_field(PythonRequirementsField)
    )

    if not reqs:
        logger.warning(
            "No third-party requirements found for the transitive closure, so a lockfile will not "
            "be generated."
        )
        return LockGoal(exit_code=1)

    input_requirements_get = Get(
        Digest, CreateDigest([FileContent("requirements.in", "\n".join(reqs).encode())])
    )
    # TODO: Figure out named_caches for pip-tools. The best would be to share the cache between
    #  Pex and Pip. Next best is a dedicated named_cache.
    pip_compile_get = Get(
        VenvPex,
        PexRequest(
            output_filename="pip_compile.pex",
            internal_only=True,
            requirements=PexRequirements(pip_tools_subsystem.all_requirements),
            # TODO: Figure out which interpreter constraints to use...Likely get it from the
            #  transitive closure. When we're doing a single global lockfile, it's fine to do that,
            #  but we need to figure out how this will work with multiple resolves.
            interpreter_constraints=InterpreterConstraints(["CPython==3.9.*"]),
            main=pip_tools_subsystem.main,
        ),
    )
    input_requirements, pip_compile = await MultiGet(input_requirements_get, pip_compile_get)

    dest = pip_tools_subsystem.lockfile_dest
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
        ),
    )
    # TODO: rewrite the file to have Pants header info, like how to regenerate the lockfile w/
    #  Pants.
    workspace.write_digest(result.output_digest)
    logger.info(f"Wrote lockfile to {dest}")

    return LockGoal(exit_code=0)


def rules():
    return collect_rules()
