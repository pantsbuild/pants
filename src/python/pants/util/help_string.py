# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast


def help_string_factory(vars: Mapping[str, Any] | None = None) -> Callable[[str], HelpString]:
    """Returns a factory function that can be used to create `HelpString` descriptors.

    The `HelpString` objects returned by the factory function can be used to refer to any object
    that exists in the namespspace provided by `vars`

    When `vars` is `None`, a reference is kept to the global namespace where `help_string_generator()`
    is called, but the values are only retrieved at evaluation time.

    In practice, this allows `help` literals to refer to properties of global classes that are
    defined later in the same file, allowing for help strings to refer to actual `alias`es.
    """
    _vars: Mapping[str, Any]

    if vars is None:
        frame: Any = inspect.currentframe()
        _vars = frame.f_back.f_globals
    else:
        _vars = vars

    def help_string(payload: str) -> HelpString:
        return HelpString(_vars, payload)

    return help_string


def help_string(payload: str) -> HelpString:
    """Returns a `HelpString`, a string descriptor that can be used to refer to properties of global
    classes that are defined later in the same file, allowing for help strings to refer to actual
    `alias`es."""
    vars = cast(Any, inspect.currentframe()).f_back.f_globals
    return help_string_factory(vars)(payload)


@dataclass(frozen=True)
class HelpString:
    """`str` descriptor that formats its `payload` based on the variables stored by `_vars`."""

    _vars: Mapping[str, Any]
    payload: str

    def __get__(self, obj, objtype=None) -> str:
        return self.payload.format(**self._vars)
