# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod


class BuildFileTargetFactory(ABC):
    """An object that can hydrate target types from BUILD files."""

    @property
    @abstractmethod
    def target_types(self):
        """The set of target types this factory can produce.

        :rytpe: :class:`collections.Iterable` of :class:`pants.build_graph.target.Target` types.
        """
