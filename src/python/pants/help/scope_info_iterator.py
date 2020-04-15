# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Set, Type

from pants.option.global_options import GlobalOptions
from pants.option.parser_hierarchy import enclosing_scope
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin


@dataclass(frozen=True)
class ScopeInfoIterator:
    """Provides relevant ScopeInfo instances in a useful order."""

    scope_to_info: Dict[str, ScopeInfo]
    v2_help: bool = False

    def iterate(self, scopes: Set[str]) -> Iterator[ScopeInfo]:
        """Yields ScopeInfo instances for the specified scopes, plus relevant related scopes.

        Relevant scopes are:
          - All tasks in a requested goal.
          - All subsystems tied to a request scope.

        Yields in a sensible order: Sorted by scope, but with subsystems tied to a request scope
        following that scope, e.g.,

        goal1
        goal1.task11
        subsys.goal1.task11
        goal1.task12
        goal2.task21
        ...
        """

        scope_infos: List[ScopeInfo] = []

        if self.v2_help:
            scope_infos.extend(sorted(self.scope_to_info[s] for s in scopes))
        else:
            scope_infos.extend(self.scope_to_info[s] for s in self._expand_tasks(scopes))

        for info in self._expand_subsystems(scope_infos):
            yield info

    def _expand_tasks(self, scopes: Set[str]) -> List[str]:
        """Add all tasks in any requested goals.

        Returns the requested scopes, plus the added tasks, sorted by scope name.
        """
        expanded_scopes = set(scopes)
        for scope, info in self.scope_to_info.items():
            if info.category == ScopeInfo.TASK:
                outer = enclosing_scope(scope)
                while outer != GLOBAL_SCOPE:
                    if outer in expanded_scopes:
                        expanded_scopes.add(scope)
                        break
                    outer = enclosing_scope(outer)
        return sorted(expanded_scopes)

    def _expand_subsystems(self, scope_infos: List[ScopeInfo]) -> Iterator[ScopeInfo]:
        """Add all subsystems tied to a scope, right after that scope."""

        # Get non-global subsystem dependencies of the specified subsystem client.
        def subsys_deps(subsystem_client_cls: Type[Any]) -> Iterator[ScopeInfo]:
            for dep in subsystem_client_cls.subsystem_dependencies_iter():
                if dep.scope != GLOBAL_SCOPE:
                    yield self.scope_to_info[dep.options_scope]
                    for x in subsys_deps(dep.subsystem_cls):
                        yield x

        for scope_info in scope_infos:
            yield scope_info
            if scope_info.optionable_cls is not None:
                # We don't currently subclass GlobalOptions, and I can't think of any reason why
                # we would, but might as well be robust.
                if issubclass(scope_info.optionable_cls, GlobalOptions):
                    # We were asked for global help, so also yield for all global subsystems.
                    for scope, info in self.scope_to_info.items():
                        if (
                            info.category == ScopeInfo.SUBSYSTEM
                            and enclosing_scope(scope) == GLOBAL_SCOPE
                        ):
                            yield info
                            if info.optionable_cls is not None:
                                for subsys_dep in subsys_deps(info.optionable_cls):
                                    yield subsys_dep
                elif issubclass(scope_info.optionable_cls, SubsystemClientMixin):
                    for subsys_dep in subsys_deps(scope_info.optionable_cls):
                        yield subsys_dep
