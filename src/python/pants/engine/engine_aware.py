# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from pants.engine.internals import native_engine
from pants.util.logging import LogLevel

if TYPE_CHECKING:
    from pants.engine.fs import FileDigest, Snapshot


class EngineAwareParameter(ABC):
    """A marker class for rule parameters that allows sending additional metadata to the engine.

    When Pants executes a rule, the engine will call this marker class's methods on the rule's
    inputs to see if they implement any of the methods. If the method returns `None`, the engine
    will do nothing; otherwise, it will use the additional metadata provided.
    """

    def debug_hint(self) -> str | None:
        """If implemented, this string will be shown in `@rule` debug contexts if that rule takes
        the annotated type as a parameter."""
        return None

    def metadata(self) -> dict[str, Any] | None:
        """If implemented, adds arbitrary key-value pairs to the `metadata` entry of the `@rule`.

        If multiple Params to a `@rule` have metadata, the metadata will be merged in a
        deterministic but unspecified order.
        """

        return None


class EngineAwareReturnType(ABC):
    """A marker class for types that are returned by rules to allow sending additional metadata to
    the engine.

    When Pants finishes executing a rule, the engine will call this marker class's methods to see if
    it implements any of the methods. If the method returns `None`, the engine will do nothing;
    otherwise, it will use the additional metadata provided.
    """

    def level(self) -> LogLevel | None:
        """If implemented, this method will modify the level of the workunit associated with any
        `@rule`s that return the annotated type.

        For instance, this can be used to change a workunit that would normally be at `Debug` level
        to `Warn` if an anomalous condition occurs within the `@rule`.
        """
        return None

    def message(self) -> str | None:
        """If implemented, this adds a result message to the workunit for any `@rule`'s that return
        the annotated type.

        The final message will take the form "Completed: <Rule description> - <this method's return
        value>". This method may use newlines.
        """
        return None

    def cacheable(self) -> bool:
        """Allows a return type to be conditionally marked uncacheable.

        An uncacheable value is recomputed in each Session: this can be useful if the level or
        message should be rendered as sideeffects in each Session.
        """
        return True

    def artifacts(self) -> dict[str, FileDigest | Snapshot] | None:
        """If implemented, this sets the `artifacts` entry for the workunit of any `@rule`'s that
        return the annotated type.

        `artifacts` is a mapping of arbitrary string keys to `Snapshot`s or `FileDigest`s.
        """
        return None

    def metadata(self) -> dict[str, Any] | None:
        """If implemented, adds arbitrary key-value pairs to the `metadata` entry of the `@rule`.

        If a @rule has `metadata` supplied by `EngineAwareParameter`s, the data will be merged, with
        only colliding keys overwritten.
        """

        return None


class SideEffecting(ABC):
    """Marks a class as providing side-effecting APIs, which are handled specially in @rules.

    Implementers of SideEffecting classes should ensure that `def side_effected` is called before
    the class causes side-effects.

    Note that logging is _not_ considered to be a side-effect, but other types of output to stdio
    are.
    """

    # Used to disable enforcement of effects in tests.
    _enforce_effects: bool

    def side_effected(self) -> None:
        # NB: This method is implemented by manipulating a thread/task-local property which will
        # only be in scope if the SideEffecting property has correctly been identified on a @rule
        # Parameter.
        #
        # TODO: As part of #10542, it's possible that all side-effecting methods will need to
        # become async instead, which would avoid the need for a thread/task-local.
        if self._enforce_effects:
            native_engine.task_side_effected()
