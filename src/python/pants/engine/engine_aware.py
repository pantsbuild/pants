# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC
from typing import Dict, Optional

from pants.engine.fs import Digest
from pants.util.logging import LogLevel


class EngineAware(ABC):
    """`EngineAware` is a marker class used to send metadata about types serving as the input
    parameters or return type of an `@rule` to the engine.

    Every method defined on `EngineAware` has a return type `Optional[T]` and
    a default implementation that returns None. When Pants executes a goal,
    the engine will call these methods on rule inputs and outputs that subclass
    EngineAware. If the method call returns `None`, the engine will do nothing,
    but will change its behavior in some way if the method returns a non-`None` value.

    `EngineAware` subclasses may implement whichever subset of these methods
    they need, leaving the others alone. Subclassing `EngineAware` and
    implementing none of these methods is equivalent to not subclassing
    `EngineAware` at all.
    """

    def level(self) -> Optional[LogLevel]:
        """If implemented for a type returned by an `@rule`, this method will modify the level of
        the workunit associated with that `@rule`.

        For instance, this can be used to change a workunit that would normally be at `Debug` level
        to `Warn` if an anomalous condition occurs within the `@rule`, leaving it alone otherwise.
        """
        return None

    def message(self) -> Optional[str]:
        """If implemented for a type returned by an `@rule`, sets an optional result message on the
        workunit for that `@rule`."""
        return None

    def artifacts(self) -> Optional[Dict[str, Digest]]:
        """If implemented on a type returned by an `@rule`, sets the `artifacts` entry of that
        `@rule`'s workunit.

        `artifacts` is a mapping of arbitrary string keys to `Digest`s.
        """
        return None

    def debug_hint(self) -> Optional[str]:
        """If implemented on an input parameter to an `@rule`, this string will be shown in certain
        `@rule` debug contexts in the engine."""
        return None
