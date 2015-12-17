# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.parser_hierarchy import enclosing_scope
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin


class ScopeInfoIterator(object):
  """Provides relevant ScopeInfo instances in a useful order."""

  def __init__(self, scope_to_info):
    """
    :param dict scope_to_info: A map of scope name -> ScopeInfo instance.
    """
    self._scope_to_info = scope_to_info

  def iterate(self, scopes):
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
    scope_infos = [self._scope_to_info[s] for s in self._expand_tasks(scopes)]
    if scope_infos:
      for scope_info in self._expand_subsystems(scope_infos):
        yield scope_info

  def _expand_tasks(self, scopes):
    """Add all tasks in any requested goals.

    Returns the requested scopes, plus the added tasks, sorted by scope name.
    """
    expanded_scopes = set(scopes)
    for scope, info in self._scope_to_info.items():
      if info.category == ScopeInfo.TASK:
        outer = enclosing_scope(scope)
        while outer != GLOBAL_SCOPE:
          if outer in expanded_scopes:
            expanded_scopes.add(scope)
            break
          outer = enclosing_scope(outer)
    return sorted(expanded_scopes)

  def _expand_subsystems(self, scope_infos):
    """Add all subsystems tied to a scope, right after that scope."""

    # Get non-global subsystem dependencies of the specified subsystem client.
    def subsys_deps(subsystem_client_cls):
      for dep in subsystem_client_cls.subsystem_dependencies_iter():
        if dep.scope != GLOBAL_SCOPE:
          yield self._scope_to_info[dep.options_scope()]
          for x in subsys_deps(dep.subsystem_cls):
            yield x

    for scope_info in scope_infos:
      yield scope_info
      if scope_info.optionable_cls is not None:
        # We don't currently subclass GlobalOptionsRegistrar, and I can't think of any reason why
        # we would, but might as well be robust.
        if issubclass(scope_info.optionable_cls, GlobalOptionsRegistrar):
          # We were asked for global help, so also yield for all global subsystems.
          for scope, info in self._scope_to_info.items():
            if info.category == ScopeInfo.SUBSYSTEM and enclosing_scope(scope) == GLOBAL_SCOPE:
              yield info
              for subsys_dep in subsys_deps(info.optionable_cls):
                yield subsys_dep
        elif issubclass(scope_info.optionable_cls, SubsystemClientMixin):
          for subsys_dep in subsys_deps(scope_info.optionable_cls):
            yield subsys_dep
