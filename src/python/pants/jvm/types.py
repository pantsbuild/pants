# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.collection import DeduplicatedCollection


@dataclass(frozen=True)
class Coordinate:
    """A single Maven-style coordinate for a JVM dependency."""

    # TODO: parse and validate the input into individual coordinate
    # components, then re-expose the string coordinate as a property
    # or __str__.
    coord: str


class Coordinates(DeduplicatedCollection[Coordinate]):
    """An ordered list of MavenCoord."""
