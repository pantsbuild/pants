# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import TYPE_CHECKING

from pants.engine.internals.native_engine import EngineError as EngineError  # noqa: F401
from pants.engine.internals.native_engine import (  # noqa: F401
    IncorrectProductError as IncorrectProductError,
)
from pants.engine.internals.native_engine import IntrinsicError as IntrinsicError  # noqa: F401

if TYPE_CHECKING:
    from pants.engine.internals.native_engine import PyFailure


class PantsException(Exception):
    """Base exception type for Pants."""


class TargetDefinitionException(PantsException):
    """Indicates an invalid target definition.

    :API: public
    """

    def __init__(self, target, msg):
        """
        :param target: the target in question
        :param string msg: a description of the target misconfiguration
        """
        super().__init__(f"Invalid target {target}: {msg}")


class BuildConfigurationError(PantsException):
    """Indicates an error in a pants installation's configuration."""


class BackendConfigurationError(BuildConfigurationError):
    """Indicates a plugin backend with a missing or malformed register module."""


class MappingError(PantsException):
    """Indicates an error mapping addressable objects."""


class RuleTypeError(PantsException):
    """Invalid @rule implementation."""


class NativeEngineFailure(Exception):
    """A wrapper around a `Failure` instance.

    The failure instance being wrapped can come from an exception raised in a rule. When this
    failure is returned to a requesting rule it is first unwrapped so the original exception will be
    presented in the rule, thus the `NativeEngineFailure` exception will not be seen in rule code.

    This is different from the other `EngineError` based exceptions which doesn't originate from
    rule code.

    TODO: This type is defined in Python because pyo3 doesn't support declaring Exceptions with
    additional fields. See https://github.com/PyO3/pyo3/issues/295
    """

    def __init__(self, msg: str, failure: PyFailure) -> None:
        super().__init__(msg)
        self.failure = failure
