# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.python.rules.pex import Pex, PexRequest, PexRequirements
from pants.backend.python.rules.pex_environment import PexEnvironment
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import PythonSourceFiles, PythonSourceFilesRequest
from pants.backend.python.subsystems.ipython import IPython
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class PythonRepl(ReplImplementation):
    name = "python"


@rule(level=LogLevel.DEBUG)
async def create_python_repl_request(repl: PythonRepl, pex_env: PexEnvironment) -> ReplRequest:
    requirements_request = Get(
        Pex,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(
            Addresses(tgt.address for tgt in repl.targets), internal_only=True
        ),
    )
    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(repl.targets, include_files=True)
    )
    requirements_pex, sources = await MultiGet(requirements_request, sources_request)
    merged_digest = await Get(
        Digest, MergeDigests((requirements_pex.digest, sources.source_files.snapshot.digest))
    )

    chrooted_source_roots = [repl.in_chroot(sr) for sr in sources.source_roots]
    env = {**pex_env.environment_dict, "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots)}

    return ReplRequest(digest=merged_digest, args=(repl.in_chroot(requirements_pex.name),), env=env)


class IPythonRepl(ReplImplementation):
    name = "ipython"


@rule(level=LogLevel.DEBUG)
async def create_ipython_repl_request(
    repl: IPythonRepl, ipython: IPython, pex_env: PexEnvironment
) -> ReplRequest:
    # Note that we get an intermediate PexRequest here (instead of going straight to a Pex)
    # so that we can get the interpreter constraints for use in ipython_request.
    requirements_pex_request = await Get(
        PexRequest,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(
            Addresses(tgt.address for tgt in repl.targets), internal_only=True
        ),
    )

    requirements_request = Get(Pex, PexRequest, requirements_pex_request)

    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(repl.targets, include_files=True)
    )

    ipython_request = Get(
        Pex,
        PexRequest(
            output_filename="ipython.pex",
            entry_point=ipython.entry_point,
            requirements=PexRequirements(ipython.all_requirements),
            interpreter_constraints=requirements_pex_request.interpreter_constraints,
            internal_only=True,
        ),
    )

    requirements_pex, sources, ipython_pex = await MultiGet(
        requirements_request, sources_request, ipython_request
    )
    merged_digest = await Get(
        Digest,
        MergeDigests(
            (requirements_pex.digest, sources.source_files.snapshot.digest, ipython_pex.digest)
        ),
    )

    args: Tuple[str, ...] = (repl.in_chroot(ipython_pex.name),)
    if ipython.options.ignore_cwd:
        args = args + ("--ignore-cwd",)

    chrooted_source_roots = [repl.in_chroot(sr) for sr in sources.source_roots]
    env = {
        **pex_env.environment_dict,
        "PEX_PATH": repl.in_chroot(requirements_pex_request.output_filename),
        "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots),
    }

    return ReplRequest(digest=merged_digest, args=args, env=env)


def rules():
    return [
        *collect_rules(),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
    ]
