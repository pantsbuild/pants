# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import logging
import site
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from packaging.requirements import Requirement

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.core.util_rules.environments import determine_bootstrap_environment
from pants.engine.collection import DeduplicatedCollection
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.environment import EnvironmentName
from pants.engine.internals.selectors import Params
from pants.engine.internals.session import SessionValues
from pants.engine.platform import Platform
from pants.engine.process import (
    ProcessCacheScope,
    ProcessExecutionEnvironment,
    execute_process_or_raise,
)
from pants.engine.rules import QueryRule, collect_rules, implicitly, rule
from pants.init.bootstrap_scheduler import BootstrapScheduler
from pants.option.global_options import GlobalOptions, KeepSandboxes
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
    request: PluginsRequest, global_options: GlobalOptions,
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
                description=f"Resolving plugins: {', '.join(req_strings)}",
                inject_env={"PIP_VERBOSE": "9"},                
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


class PluginResolver:
    """Encapsulates the state of plugin loading.

    Plugin loading is inherently stateful, and so the system enviroment on `sys.path` will be
    mutatetd by  each call to `PluginResolver.resolve`.
    """

    def __init__(
        self,
        scheduler: BootstrapScheduler,
        interpreter_constraints: InterpreterConstraints | None = None,
        distribution_constraints_override: Iterable[str] | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._interpreter_constraints = interpreter_constraints
        self._distribution_constraints_override: list[str] | None = sorted(distribution_constraints_override) if distribution_constraints_override is not None else None

    def resolve(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        requirements: Iterable[str] = (),
    ) -> None:
        """Resolves any configured plugins and adds them to the sys.path as a side effect."""

        def to_requirement(d):
            return f"{d.name}=={d.version}"

        distributions: list[importlib.metadata.Distribution]
        if self._distribution_constraints_override is None:
            distributions = list(importlib.metadata.distributions())
        else:
            distributions = []
            for dist_name in self._distribution_constraints_override:
                distributions.append(importlib.metadata.distribution(dist_name))

        request = PluginsRequest(
            self._interpreter_constraints,
            tuple(to_requirement(dist) for dist in distributions),
            tuple(requirements),
            
        )
        logger.info(f"PluginsRequest={request}")

        for resolved_plugin_location in self._resolve_plugins(options_bootstrapper, env, request):
            # Activate any .pth files plugin wheels may have.
            site.addsitedir(resolved_plugin_location)

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
        process_execution_environment = ProcessExecutionEnvironment(
            environment_name=None,
            platform=Platform.create_for_localhost().value,
            remote_execution=False,
            remote_execution_extra_platform_properties=(),
            execute_in_workspace=False,
            keep_sandboxes=KeepSandboxes.on_failure.value,
            docker_image=None,
        )
        params = Params(
            request, determine_bootstrap_environment(session), process_execution_environment
        )
        return cast(
            ResolvedPluginDistributions,
            session.product_request(ResolvedPluginDistributions, [params])[0],
        )


def rules():
    return [
        QueryRule(ResolvedPluginDistributions, [PluginsRequest, EnvironmentName]),
        *collect_rules(),
    ]
