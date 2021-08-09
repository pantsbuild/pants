# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, ClassVar, cast

from pants.option.option_value_container import OptionValueContainer
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo


# TODO: Unite Optionable and Subsytem, since we no longer have any othe subtypes of
#  Optionable, and Subsystem is now sufficiently trivial.
class Subsystem(Optionable):
    """A separable piece of functionality that may be reused across multiple tasks or other code.

    Subsystems encapsulate the configuration and initialization of things like JVMs,
    Python interpreters, SCMs and so on.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.

    :API: public
    """

    scope: str
    options: OptionValueContainer

    help: ClassVar[str]

    @classmethod
    def get_scope_info(cls) -> ScopeInfo:
        cls.validate_scope_name_component(cast(str, cls.options_scope))
        return super().get_scope_info()

    def __init__(self, scope: str, options: OptionValueContainer) -> None:
        super().__init__()
        self.scope = scope
        self.options = options

    def __eq__(self, other: Any) -> bool:
        if type(self) != type(other):
            return False
        return bool(self.scope == other.scope and self.options == other.options)
