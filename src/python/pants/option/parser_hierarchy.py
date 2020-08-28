# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from typing import Dict, Iterable, Iterator, Mapping

from pants.option.config import Config
from pants.option.parser import Parser
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo


class InvalidScopeError(Exception):
    pass


_empty_scope_component_re = re.compile(r"\.\.")


def _validate_full_scope(scope: str) -> None:
    if _empty_scope_component_re.search(scope):
        raise InvalidScopeError(f"full scope '{scope}' has at least one empty component")


def enclosing_scope(scope: str) -> str:
    """Utility function to return the scope immediately enclosing a given scope."""
    _validate_full_scope(scope)
    return scope.rpartition(".")[0]


def all_enclosing_scopes(scope: str, *, allow_global: bool = True) -> Iterator[str]:
    """Utility function to return all scopes up to the global scope enclosing a given scope."""

    _validate_full_scope(scope)

    def scope_within_range(tentative_scope: str) -> bool:
        if not allow_global and tentative_scope == GLOBAL_SCOPE:
            return False
        return True

    while scope_within_range(scope):
        yield scope
        if scope == GLOBAL_SCOPE:
            return
        scope = enclosing_scope(scope)


class ParserHierarchy:
    """A hierarchy of scoped Parser instances.

    A scope is a dotted string: E.g., compile.java. In this example the compile.java scope is
    enclosed in the compile scope, which is enclosed in the global scope (represented by an empty
    string.)
    """

    def __init__(
        self,
        env: Mapping[str, str],
        config: Config,
        scope_infos: Iterable[ScopeInfo],
    ) -> None:
        # Sorting ensures that ancestors precede descendants.
        scope_infos = sorted(set(list(scope_infos)), key=lambda si: si.scope)
        self._parser_by_scope: Dict[str, Parser] = {}
        for scope_info in scope_infos:
            scope = scope_info.scope
            parent_parser = (
                None if scope == GLOBAL_SCOPE else self._parser_by_scope[enclosing_scope(scope)]
            )
            self._parser_by_scope[scope] = Parser(env, config, scope_info, parent_parser)

    def get_parser_by_scope(self, scope: str) -> Parser:
        try:
            return self._parser_by_scope[scope]
        except KeyError:
            raise Config.ConfigValidationError(f"No such options scope: {scope}")

    def walk(self, callback):
        """Invoke callback on each parser, in pre-order depth-first order."""
        self._parser_by_scope[GLOBAL_SCOPE].walk(callback)
