# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from colors import cyan, green, magenta, red, yellow


class MaybeColor:
    """A mixin to allow classes to optionally colorize their output."""

    def __init__(self, color: bool) -> None:
        self._color = color
        noop = lambda x: x
        self.maybe_cyan = cyan if color else noop
        self.maybe_green = green if color else noop
        self.maybe_red = red if color else noop
        self.maybe_magenta = magenta if color else noop
        self.maybe_yellow = yellow if color else noop

    def _format_did_you_mean_matches(self, did_you_mean: List[str]) -> str:
        if len(did_you_mean) == 1:
            formatted_candidates = self.maybe_cyan(did_you_mean[0])
        elif len(did_you_mean) == 2:
            formatted_candidates = " or ".join(self.maybe_cyan(g) for g in did_you_mean)
        else:
            formatted_candidates = (
                f"{', '.join(self.maybe_cyan(g) for g in did_you_mean[:-1])}"
                f", or {did_you_mean[-1]}"
            )
        return str(formatted_candidates)

    @property
    def color(self) -> bool:
        return self._color
