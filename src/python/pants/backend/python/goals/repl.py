# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.util_rules.pex import Pex, PexRequest, pex_path_closure
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.repl import ReplImplementation, ReplRequest
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
            (tgt.address for tgt in repl.targets), internal_only=True
        ),
    )
    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(repl.targets, include_files=True)
    )
    requirements_pex, sources = await MultiGet(requirements_request, sources_request)
    merged_digest = await Get(
        Digest, MergeDigests((requirements_pex.digest, sources.source_files.snapshot.digest))
    )

    complete_pex_env = pex_env.in_workspace()
    args = complete_pex_env.create_argv(
        repl.in_chroot(requirements_pex.name), python=requirements_pex.python
    )

    chrooted_source_roots = [repl.in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **complete_pex_env.environment_dict(python_configured=requirements_pex.python is not None),
        "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots),
    }

    return ReplRequest(digest=merged_digest, args=args, extra_env=extra_env)


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
            (tgt.address for tgt in repl.targets), internal_only=True
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
            main=ipython.main,
            requirements=ipython.pex_requirements(),
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

    complete_pex_env = pex_env.in_workspace()
    args = list(
        complete_pex_env.create_argv(repl.in_chroot(ipython_pex.name), python=ipython_pex.python)
    )
    if ipython.options.ignore_cwd:
        args.append("--ignore-cwd")

    chrooted_source_roots = [repl.in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **complete_pex_env.environment_dict(python_configured=ipython_pex.python is not None),
        "PEX_PATH": ":".join(repl.in_chroot(p.name) for p in pex_path_closure([requirements_pex])),
        "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots),
    }

    return ReplRequest(digest=merged_digest, args=args, extra_env=extra_env)


def rules():
    return [
        *collect_rules(),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
    ]
