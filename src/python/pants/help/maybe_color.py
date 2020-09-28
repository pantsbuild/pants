# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from colors import cyan, green, magenta, red


class MaybeColor:
    """A mixin to allow classes to optionally colorize their output."""

    def __init__(self, color: bool) -> None:
        self._color = color
        noop = lambda x: x
        self.maybe_cyan = cyan if color else noop
        self.maybe_green = green if color else noop
        self.maybe_red = red if color else noop
        self.maybe_magenta = magenta if color else noop

    @property
    def color(self) -> bool:
        return self._color
