# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os

from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import (
    InterpreterConstraintsRequest,
    RequirementsPexRequest,
)
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
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

    addresses = tuple(tgt.address for tgt in repl.targets)
    interpreter_constraints = await Get(
        InterpreterConstraints, InterpreterConstraintsRequest(addresses)
    )
    requirements_request = Get(Pex, RequirementsPexRequest(addresses, internal_only=True))

    local_dists_request = Get(
        LocalDistsPex,
        LocalDistsPexRequest(
            Addresses(tgt.address for tgt in repl.targets),
            internal_only=True,
            interpreter_constraints=interpreter_constraints,
        ),
    )

    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(repl.targets, include_files=True)
    )

    requirements_pex, local_dists, sources = await MultiGet(
        requirements_request, local_dists_request, sources_request
    )
    merged_digest = await Get(
        Digest,
        MergeDigests(
            (requirements_pex.digest, local_dists.pex.digest, sources.source_files.snapshot.digest)
        ),
    )

    complete_pex_env = pex_env.in_workspace()
    args = complete_pex_env.create_argv(
        repl.in_chroot(requirements_pex.name), python=requirements_pex.python
    )

    chrooted_source_roots = [repl.in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **complete_pex_env.environment_dict(python_configured=requirements_pex.python is not None),
        "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots),
        "PEX_PATH": repl.in_chroot(local_dists.pex.name),
    }

    return ReplRequest(digest=merged_digest, args=args, extra_env=extra_env)


class IPythonRepl(ReplImplementation):
    name = "ipython"


@rule(level=LogLevel.DEBUG)
async def create_ipython_repl_request(
    repl: IPythonRepl, ipython: IPython, pex_env: PexEnvironment
) -> ReplRequest:
    addresses = tuple(tgt.address for tgt in repl.targets)
    interpreter_constraints = await Get(
        InterpreterConstraints, InterpreterConstraintsRequest(addresses)
    )
    requirements_request = Get(Pex, RequirementsPexRequest(addresses, internal_only=True))

    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(repl.targets, include_files=True)
    )

    ipython_request = Get(
        Pex,
        PexRequest(
            output_filename="ipython.pex",
            main=ipython.main,
            requirements=ipython.pex_requirements(),
            interpreter_constraints=interpreter_constraints,
            internal_only=True,
        ),
    )

    requirements_pex, sources, ipython_pex = await MultiGet(
        requirements_request, sources_request, ipython_request
    )

    local_dists = await Get(
        LocalDistsPex,
        LocalDistsPexRequest(
            [tgt.address for tgt in repl.targets],
            internal_only=True,
            interpreter_constraints=interpreter_constraints,
            sources=sources,
        ),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                requirements_pex.digest,
                local_dists.pex.digest,
                local_dists.remaining_sources.source_files.snapshot.digest,
                ipython_pex.digest,
            )
        ),
    )

    complete_pex_env = pex_env.in_workspace()
    args = list(
        complete_pex_env.create_argv(repl.in_chroot(ipython_pex.name), python=ipython_pex.python)
    )
    if ipython.options.ignore_cwd:
        args.append("--ignore-cwd")

    chrooted_source_roots = [repl.in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **complete_pex_env.environment_dict(python_configured=ipython_pex.python is not None),
        "PEX_PATH": os.pathsep.join(
            [
                repl.in_chroot(requirements_pex.name),
                repl.in_chroot(local_dists.pex.name),
            ]
        ),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(chrooted_source_roots),
    }

    return ReplRequest(digest=merged_digest, args=args, extra_env=extra_env)


def rules():
    return [
        *collect_rules(),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
    ]
