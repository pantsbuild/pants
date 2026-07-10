# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.engine.environment import EnvironmentName
from pants.engine.process import ProcessCacheScope, execute_process_or_raise
from pants.engine.rules import QueryRule, collect_rules, implicitly, rule
from pants.init.plugin_resolver import PluginsRequest, ResolvedPluginDistributions
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel


@rule
async def resolve_plugins(
    request: PluginsRequest,
    global_options: GlobalOptions,
) -> ResolvedPluginDistributions:
    """This rule resolves plugins using a VenvPex, and exposes the absolute paths of their dists.

    NB: This relies on the fact that PEX constructs venvs in a stable location (within the
    `named_caches` directory), but consequently needs to disable the process cache: see the
    ProcessCacheScope reference in the body.
    """
    req_strings = sorted(global_options.plugins + request.requirements)

    requirements = PexRequirements(
        req_strings_or_addrs=req_strings,
        constraints_strings=(str(constraint) for constraint in request.constraints),
        description_of_origin="configured Pants plugins",
    )
    if not requirements:
        return ResolvedPluginDistributions()

    python: PythonExecutable | None = None
    if not request.interpreter_constraints:
        python = PythonExecutable.fingerprinted(
            sys.executable, ".".join(map(str, sys.version_info[:3])).encode("utf8")
        )

    plugins_pex = await create_venv_pex(
        **implicitly(
            PexRequest(
                output_filename="pants_plugins.pex",
                internal_only=True,
                python=python,
                requirements=requirements,
                interpreter_constraints=request.interpreter_constraints or InterpreterConstraints(),
                additional_args=("--preserve-pip-download-log", "pex-pip-download.log"),
                description=f"Resolving plugins: {', '.join(req_strings)}",
            )
        )
    )

    # NB: We run this Process per-restart because it (intentionally) leaks named cache
    # paths in a way that invalidates the Process-cache. See the method doc.
    cache_scope = (
        ProcessCacheScope.PER_SESSION
        if global_options.plugins_force_resolve
        else ProcessCacheScope.PER_RESTART_SUCCESSFUL
    )

    plugins_process_result = await execute_process_or_raise(
        **implicitly(
            VenvPexProcess(
                plugins_pex,
                argv=("-c", "import os, site; print(os.linesep.join(site.getsitepackages()))"),
                description="Extracting plugin locations",
                level=LogLevel.DEBUG,
                cache_scope=cache_scope,
            )
        )
    )
    return ResolvedPluginDistributions(plugins_process_result.stdout.decode().strip().split("\n"))


def rules():
    return [
        QueryRule(ResolvedPluginDistributions, [PluginsRequest, EnvironmentName]),
        *collect_rules(),
    ]
