# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import site
import sys
from dataclasses import dataclass
from typing import Iterable, Optional, cast

from pkg_resources import Requirement, WorkingSet
from pkg_resources import working_set as global_working_set

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.core.util_rules.environments import determine_bootstrap_environment
from pants.engine.collection import DeduplicatedCollection
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.environment import EnvironmentName
from pants.engine.internals.selectors import Params
from pants.engine.internals.session import SessionValues
from pants.engine.process import ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, QueryRule, collect_rules, rule
from pants.init.bootstrap_scheduler import BootstrapScheduler
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginsRequest:
    # Interpreter constraints to resolve for, or None to resolve for the interpreter that Pants is
    # running under.
    interpreter_constraints: InterpreterConstraints | None
    # Requirement constraints to resolve with. If plugins will be loaded into the global working_set
    # (i.e., onto the `sys.path`), then these should be the current contents of the working_set.
    constraints: tuple[Requirement, ...]
    # Backend requirements to resolve
    requirements: tuple[str, ...]


class ResolvedPluginDistributions(DeduplicatedCollection[str]):
    sort_input = True


@rule
async def resolve_plugins(
    request: PluginsRequest, global_options: GlobalOptions
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

    plugins_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="pants_plugins.pex",
            internal_only=True,
            python=python,
            requirements=requirements,
            interpreter_constraints=request.interpreter_constraints or InterpreterConstraints(),
            description=f"Resolving plugins: {', '.join(req_strings)}",
        ),
    )

    # NB: We run this Process per-restart because it (intentionally) leaks named cache
    # paths in a way that invalidates the Process-cache. See the method doc.
    cache_scope = (
        ProcessCacheScope.PER_SESSION
        if global_options.plugins_force_resolve
        else ProcessCacheScope.PER_RESTART_SUCCESSFUL
    )

    plugins_process_result = await Get(
        ProcessResult,
        VenvPexProcess(
            plugins_pex,
            argv=("-c", "import os, site; print(os.linesep.join(site.getsitepackages()))"),
            description="Extracting plugin locations",
            level=LogLevel.DEBUG,
            cache_scope=cache_scope,
        ),
    )
    return ResolvedPluginDistributions(plugins_process_result.stdout.decode().strip().split("\n"))


class PluginResolver:
    """Encapsulates the state of plugin loading for the given WorkingSet.

    Plugin loading is inherently stateful, and so this class captures the state of the WorkingSet at
    creation time, even though it will be mutated by each call to `PluginResolver.resolve`. This
    makes the inputs to each `resolve(..)` call idempotent, even if the output is not.
    """

    def __init__(
        self,
        scheduler: BootstrapScheduler,
        interpreter_constraints: Optional[InterpreterConstraints] = None,
        working_set: Optional[WorkingSet] = None,
    ) -> None:
        self._scheduler = scheduler
        self._working_set = working_set or global_working_set
        self._interpreter_constraints = interpreter_constraints

    def resolve(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        requirements: Iterable[str] = (),
    ) -> WorkingSet:
        """Resolves any configured plugins and adds them to the working_set."""
        request = PluginsRequest(
            self._interpreter_constraints,
            tuple(dist.as_requirement() for dist in self._working_set),
            tuple(requirements),
        )

        for resolved_plugin_location in self._resolve_plugins(options_bootstrapper, env, request):
            site.addsitedir(
                resolved_plugin_location
            )  # Activate any .pth files plugin wheels may have.
            self._working_set.add_entry(resolved_plugin_location)
        return self._working_set

    def _resolve_plugins(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        request: PluginsRequest,
    ) -> ResolvedPluginDistributions:
        session = self._scheduler.scheduler.new_session(
            "plugin_resolver",
            session_values=SessionValues(
                {
                    OptionsBootstrapper: options_bootstrapper,
                    CompleteEnvironmentVars: env,
                }
            ),
        )
        params = Params(request, determine_bootstrap_environment(session))
        return cast(
            ResolvedPluginDistributions,
            session.product_request(ResolvedPluginDistributions, [params])[0],
        )


def rules():
    return [
        QueryRule(ResolvedPluginDistributions, [PluginsRequest, EnvironmentName]),
        *collect_rules(),
    ]
