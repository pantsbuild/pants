# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from abc import ABC
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _satisfied_by(t, o):
    """Pickleable type check function."""
    return t.satisfied_by(o)


class State(ABC):
    @classmethod
    def raise_unrecognized(cls, state):
        raise ValueError("Unrecognized Node State: {}".format(state))

    @staticmethod
    def from_components(components):
        """Given the components of a State, construct the State."""
        cls, remainder = components[0], components[1:]
        return cls._from_components(remainder)

    def to_components(self):
        """Return a flat tuple containing individual pickleable components of the State.

        TODO: Consider https://docs.python.org/2.7/library/pickle.html#pickling-and-unpickling-external-objects
        for this usecase?
        """
        return (type(self),) + self._to_components()


@dataclass(frozen=True)
class Return(State):
    """Indicates that a Node successfully returned a value."""

    value: Any

    @classmethod
    def _from_components(cls, components):
        return cls(components[0])

    def _to_components(self):
        return (self.value,)


@dataclass(frozen=True)
class Throw(State):
    """Indicates that a Node should have been able to return a value, but failed."""

    exc: Any
