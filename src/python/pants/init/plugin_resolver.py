# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import logging
import site
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from packaging.requirements import Requirement

from pants.core.environments.rules import determine_bootstrap_environment
from pants.engine.collection import DeduplicatedCollection
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.selectors import Params
from pants.engine.internals.session import SessionValues
from pants.init.bootstrap_scheduler import BootstrapScheduler
from pants.init.import_util import find_matching_distributions
from pants.option.options_bootstrapper import OptionsBootstrapper

if TYPE_CHECKING:
    from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints

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


class PluginResolver:
    """Encapsulates the state of plugin loading.

    Plugin loading is inherently stateful, and so the system enviroment on `sys.path` will be
    mutated by each call to `PluginResolver.resolve`.
    """

    def __init__(
        self,
        scheduler: Callable[[], BootstrapScheduler],
        interpreter_constraints: InterpreterConstraints | None = None,
        inherit_existing_constraints: bool = True,
    ) -> None:
        # The scheduler is built lazily: it is only needed to pex-resolve distribution plugins,
        # which most repos do not configure. Deferring it keeps the second rule-graph build and
        # its backend load off the critical path when there is nothing to resolve.
        self._scheduler_factory = scheduler
        self._scheduler_instance: BootstrapScheduler | None = None
        self._interpreter_constraints = interpreter_constraints
        self._inherit_existing_constraints = inherit_existing_constraints

    @property
    def _scheduler(self) -> BootstrapScheduler:
        if self._scheduler_instance is None:
            self._scheduler_instance = self._scheduler_factory()
        return self._scheduler_instance

    def resolve(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        requirements: Iterable[str] = (),
    ) -> list[str]:
        """Resolves any configured plugins and adds them to the sys.path as a side effect."""
        requirements = tuple(requirements)
        # `resolve_plugins` resolves `[GLOBAL].plugins` plus these backend requirements. With
        # neither, it would resolve nothing, so short-circuit before building the bootstrap
        # scheduler (which exists only to run this resolution).
        configured_plugins = options_bootstrapper.bootstrap_options.for_global_scope().plugins
        if not configured_plugins and not requirements:
            return []

        def to_requirement(d):
            return f"{d.name}=={d.version}"

        distributions: list[importlib.metadata.Distribution] = []
        if self._inherit_existing_constraints:
            distributions = list(find_matching_distributions(None))

        request = PluginsRequest(
            self._interpreter_constraints,
            tuple(to_requirement(dist) for dist in distributions),
            tuple(requirements),
        )

        result = []
        for resolved_plugin_location in self._resolve_plugins(options_bootstrapper, env, request):
            # Activate any .pth files plugin wheels may have.
            orig_sys_path_len = len(sys.path)
            site.addsitedir(resolved_plugin_location)
            if len(sys.path) > orig_sys_path_len:
                result.append(resolved_plugin_location)

        return result

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
            session.product_request(ResolvedPluginDistributions, params)[0],
        )
