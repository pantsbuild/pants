# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import site
import sys
from typing import Optional, TypeVar, cast

from pkg_resources import WorkingSet
from pkg_resources import working_set as global_working_set

from pants.backend.python.util_rules.pex import (
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
    VenvPex,
    VenvPexProcess,
)
from pants.engine.collection import DeduplicatedCollection
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.session import SessionValues
from pants.engine.process import ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, QueryRule, collect_rules, rule
from pants.init.bootstrap_scheduler import BootstrapScheduler
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


S = TypeVar("S", bound=Subsystem)


class ResolvedPluginDistributions(DeduplicatedCollection[str]):
    sort_input = True


@rule
async def resolve_plugins(
    interpreter_constraints: PexInterpreterConstraints, global_options: GlobalOptions
) -> ResolvedPluginDistributions:
    """This rule resolves plugins using a VenvPex, and exposes the absolute paths of their dists.

    NB: This relies on the fact that PEX constructs venvs in a stable location (within the
    `named_caches` directory), but consequently needs to disable the process cache: see the
    ProcessCacheScope reference in the body.
    """
    requirements = PexRequirements(sorted(global_options.options.plugins))
    if not requirements:
        return ResolvedPluginDistributions()

    plugins_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="pants_plugins.pex",
            internal_only=True,
            requirements=requirements,
            interpreter_constraints=interpreter_constraints,
            # The repository's constraints are not relevant here, because this resolve is mixed
            # into the Pants' process' path, and never into user code.
            apply_requirement_constraints=False,
            description=f"Resolving plugins: {', '.join(requirements)}",
        ),
    )

    # NB: We run this Process per-restart because it (intentionally) leaks named cache
    # paths in a way that invalidates the Process-cache. See the method doc.
    cache_scope = (
        ProcessCacheScope.NEVER
        if global_options.options.plugins_force_resolve
        else ProcessCacheScope.PER_RESTART
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
    def __init__(
        self,
        scheduler: BootstrapScheduler,
        interpreter_constraints: Optional[PexInterpreterConstraints] = None,
    ) -> None:
        self._scheduler = scheduler
        self._interpreter_constraints = (
            interpreter_constraints
            if interpreter_constraints is not None
            else PexInterpreterConstraints([f"=={'.'.join(map(str, sys.version_info[:3]))}"])
        )

    def resolve(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironment,
        working_set: Optional[WorkingSet] = None,
    ) -> WorkingSet:
        """Resolves any configured plugins and adds them to the global working set.

        :param working_set: The working set to add the resolved plugins to instead of the global
                            working set (for testing).
        """
        working_set = working_set or global_working_set
        for resolved_plugin_location in self._resolve_plugins(options_bootstrapper, env):
            site.addsitedir(
                resolved_plugin_location
            )  # Activate any .pth files plugin wheels may have.
            working_set.add_entry(resolved_plugin_location)
        return working_set

    def _resolve_plugins(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironment,
    ) -> ResolvedPluginDistributions:
        session = self._scheduler.scheduler.new_session(
            "plugin_resolver",
            session_values=SessionValues(
                {
                    OptionsBootstrapper: options_bootstrapper,
                    CompleteEnvironment: env,
                }
            ),
        )
        return cast(
            ResolvedPluginDistributions,
            session.product_request(ResolvedPluginDistributions, [self._interpreter_constraints])[
                0
            ],
        )


def rules():
    return [
        QueryRule(ResolvedPluginDistributions, [PexInterpreterConstraints]),
        *collect_rules(),
    ]
