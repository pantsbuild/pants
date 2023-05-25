# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable

from pants.backend.python.subsystems import ipython
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
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
from pants.core.goals.generate_lockfiles import NoCompatibleResolveException
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


def validate_compatible_resolve(root_targets: Iterable[Target], python_setup: PythonSetup) -> None:
    """Eagerly validate that all roots are compatible.

    We already end up checking this in pex_from_targets.py, but this is a more eager check so that
    we have a better error message.
    """
    root_resolves = {
        root[PythonResolveField].normalized_value(python_setup)
        for root in root_targets
        if root.has_field(PythonResolveField)
    }

    def maybe_get_resolve(t: Target) -> str | None:
        if not t.has_field(PythonResolveField):
            return None
        return t[PythonResolveField].normalized_value(python_setup)

    if len(root_resolves) > 1:
        raise NoCompatibleResolveException.bad_input_roots(
            root_targets,
            maybe_get_resolve=maybe_get_resolve,
            doc_url_slug="python-third-party-dependencies#multiple-lockfiles",
            workaround=softwrap(
                f"""
                To work around this, choose which resolve you want to use from above. Then, run
                `{bin_name()} peek :: | jq -r \'.[] | select(.resolve == "example") |
                .["address"]\' | xargs {bin_name()} repl`, where you replace "example" with the
                resolve name, and possibly replace the specs `::` with what you were using
                before. If the resolve is the `[python].default_resolve`, use
                `select(.resolve == "example" or .resolve == null)`. These queries will result in
                opening a REPL with only targets using the desired resolve.
                """
            ),
        )


class PythonRepl(ReplImplementation):
    name = "python"


@rule(level=LogLevel.DEBUG)
async def create_python_repl_request(
    request: PythonRepl, pex_env: PexEnvironment, python_setup: PythonSetup
) -> ReplRequest:
    validate_compatible_resolve(request.targets, python_setup)

    interpreter_constraints, transitive_targets = await MultiGet(
        Get(InterpreterConstraints, InterpreterConstraintsRequest(request.addresses)),
        Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses)),
    )

    requirements_request = Get(Pex, RequirementsPexRequest(request.addresses))
    local_dists_request = Get(
        LocalDistsPex,
        LocalDistsPexRequest(
            request.addresses,
            internal_only=True,
            interpreter_constraints=interpreter_constraints,
        ),
    )

    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure, include_files=True)
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
    args = complete_pex_env.create_argv(request.in_chroot(requirements_pex.name))

    chrooted_source_roots = [request.in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **complete_pex_env.environment_dict(python=requirements_pex.python),
        "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots),
        "PEX_PATH": request.in_chroot(local_dists.pex.name),
        "PEX_INTERPRETER_HISTORY": "1" if python_setup.repl_history else "0",
    }

    return ReplRequest(digest=merged_digest, args=args, extra_env=extra_env)


class IPythonRepl(ReplImplementation):
    name = "ipython"


@rule(level=LogLevel.DEBUG)
async def create_ipython_repl_request(
    request: IPythonRepl, ipython: IPython, pex_env: PexEnvironment, python_setup: PythonSetup
) -> ReplRequest:
    validate_compatible_resolve(request.targets, python_setup)

    interpreter_constraints, transitive_targets = await MultiGet(
        Get(InterpreterConstraints, InterpreterConstraintsRequest(request.addresses)),
        Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses)),
    )

    requirements_request = Get(Pex, RequirementsPexRequest(request.addresses))
    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure, include_files=True)
    )

    ipython_request = Get(
        Pex, PexRequest, ipython.to_pex_request(interpreter_constraints=interpreter_constraints)
    )

    requirements_pex, sources, ipython_pex = await MultiGet(
        requirements_request, sources_request, ipython_request
    )

    local_dists = await Get(
        LocalDistsPex,
        LocalDistsPexRequest(
            request.addresses,
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
    args = list(complete_pex_env.create_argv(request.in_chroot(ipython_pex.name)))
    if ipython.ignore_cwd:
        args.append("--ignore-cwd")

    chrooted_source_roots = [request.in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **complete_pex_env.environment_dict(python=ipython_pex.python),
        "PEX_PATH": os.pathsep.join(
            [
                request.in_chroot(requirements_pex.name),
                request.in_chroot(local_dists.pex.name),
            ]
        ),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(chrooted_source_roots),
    }

    return ReplRequest(digest=merged_digest, args=args, extra_env=extra_env)


def rules():
    return [
        *collect_rules(),
        *ipython.rules(),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
    ]
