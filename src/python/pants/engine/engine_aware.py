# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC
from typing import Dict, Optional

from pants.engine.fs import Digest
from pants.util.logging import LogLevel


class EngineAware(ABC):
    """This is a marker class used to indicate that the output of an `@rule` can send metadata about
    the rule's output to the engine.

    EngineAware defines abstract methods on the class, all of which return an Optional[T], and which
    are expected to be overridden by concrete types implementing EngineAware.
    """

    def level(self) -> Optional[LogLevel]:
        """Overrides the level of the workunit associated with this type."""
        return None

    def message(self) -> Optional[str]:
        """Sets an optional result message on the workunit."""
        return None

    def artifacts(self) -> Optional[Dict[str, Digest]]:
        """Sets a map of names to `Digest`s to appear as artifacts on the workunit."""
        return None
