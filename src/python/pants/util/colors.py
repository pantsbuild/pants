# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# See https://en.wikipedia.org/wiki/ANSI_escape_code#24-bit

import functools
import re
from typing import TYPE_CHECKING, Callable

from typing_extensions import ParamSpec


def strip_color(s: str) -> str:
    """Remove ANSI color/style sequences from a string."""
    return re.sub("\x1b\\[(.*?m)", "", s)


_P = ParamSpec("_P")


def _ansi_color(r: int, g: int, b: int) -> Callable[[Callable[_P, None]], Callable[_P, str]]:
    def decorator(func: Callable[_P, None]) -> Callable[_P, str]:
        @functools.wraps(func)
        def wrapper(s: str, *, bold: bool = False, underline: bool = False) -> str:
            return (
                f"\x1b[{'1;' if bold else ''}{'4;' if underline else ''}38;2;{r};{g};{b}m{s}\x1b[0m"
            )

        return wrapper  # type: ignore

    return decorator


@_ansi_color(0, 0, 255)
def blue(s: str, *, bold: bool = False, underline: bool = False):
    """Clear skies, tranquil oceans, and sapphires gleaming with brilliance."""

if TYPE_CHECKING:
    reveal_type(blue)

@_ansi_color(0, 255, 255)
def cyan(s: str, *, bold: bool = False, underline: bool = False):
    """Tropical waters, verdant foliage, and the vibrant plumage of exotic birds."""


@_ansi_color(0, 128, 0)
def green(s: str, *, bold: bool = False, underline: bool = False):
    """Fresh leaves, lush meadows, and emerald gemstones."""


@_ansi_color(255, 0, 255)
def magenta(s: str, *, bold: bool = False, underline: bool = False):
    """Blooming flowers, radiant sunsets, and the bold intensity of fuchsia."""


@_ansi_color(255, 165, 0)
def orange(s: str, *, bold: bool = False, underline: bool = False):
    """Zest of ripe citrus fruits, fiery autumn leaves, and the energetic glow of a setting sun."""


@_ansi_color(255, 0, 0)
def red(s: str, *, bold: bool = False, underline: bool = False):
    """Fiery sunsets, vibrant roses, and the exhilarating energy of blazing flames."""


@_ansi_color(255, 255, 0)
def yellow(s: str, *, bold: bool = False, underline: bool = False):
    """Sunshine, golden fields of daffodils, and the cheerful vibrancy of lemon zest."""
