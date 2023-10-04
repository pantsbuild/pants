# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shlex
import textwrap
from collections import abc
from typing import Any, Callable, Iterable, TypeVar

import colors
from typing_extensions import ParamSpec

from pants.engine.internals.native_engine import Digest
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


def ensure_binary(text_or_binary: bytes | str) -> bytes:
    if isinstance(text_or_binary, bytes):
        return text_or_binary
    elif isinstance(text_or_binary, str):
        return text_or_binary.encode("utf8")
    else:
        raise TypeError(f"Argument is neither text nor binary type.({type(text_or_binary)})")


def ensure_text(text_or_binary: bytes | str) -> str:
    if isinstance(text_or_binary, bytes):
        return text_or_binary.decode()
    elif isinstance(text_or_binary, str):
        return text_or_binary
    else:
        raise TypeError(f"Argument is neither text nor binary type ({type(text_or_binary)})")


def safe_shlex_split(text_or_binary: bytes | str) -> list[str]:
    """Split a string using shell-like syntax.

    Safe even on python versions whose shlex.split() method doesn't accept unicode.
    """
    value = ensure_text(text_or_binary)
    return shlex.split(value)


# `_shell_unsafe_chars_pattern` and `shell_quote` are modified from the CPython 3.6 source:
# https://github.com/python/cpython/blob/142e3c08a40c75b5788474b0defe7d5c0671f675/Lib/shlex.py#L308
_shell_unsafe_chars_pattern = re.compile(r"[^\w@%+=:,./-]").search


def shell_quote(s: str) -> str:
    """Return a shell-escaped version of the string *s*."""
    if not s:
        return "''"
    if _shell_unsafe_chars_pattern(s) is None:
        return s

    # use single quotes, and put single quotes into double quotes
    # the string $'b is then quoted as '$'"'"'b'
    return "'" + s.replace("'", "'\"'\"'") + "'"


def safe_shlex_join(arg_list: Iterable[str]) -> str:
    """Join a list of strings into a shlex-able string.

    Shell-quotes each argument with `shell_quote()`.
    """
    return " ".join(shell_quote(arg) for arg in arg_list)


def create_path_env_var(
    new_entries: Iterable[str],
    env: dict[str, str] | None = None,
    env_var: str = "PATH",
    delimiter: str = ":",
    prepend: bool = False,
):
    """Join path entries, combining with an environment variable if specified."""
    if env is None:
        env = {}

    prev_path = env.get(env_var, None)
    if prev_path is None:
        path_dirs: list[str] = []
    else:
        path_dirs = list(prev_path.split(delimiter))

    new_entries_list = list(new_entries)

    if prepend:
        path_dirs = new_entries_list + path_dirs
    else:
        path_dirs += new_entries_list

    return delimiter.join(path_dirs)


def pluralize(count: int, item_type: str, include_count: bool = True) -> str:
    """Pluralizes the item_type if the count does not equal one.

    For example `pluralize(1, 'apple')` returns '1 apple',
    while `pluralize(0, 'apple') returns '0 apples'.

    When `include_count=False` does not add the count in front of the pluralized `item_type`.

    :return The count and inflected item_type together as a string
    """

    def pluralize_string(x: str) -> str:
        if x.endswith("s"):
            return x + "es"
        elif x.endswith("y"):
            return x[:-1] + "ies"
        else:
            return x + "s"

    pluralized_item = item_type if count == 1 else pluralize_string(item_type)
    if not include_count:
        return pluralized_item
    else:
        text = f"{count} {pluralized_item}"
        return text


def comma_separated_list(items: Iterable[str]) -> str:
    items = list(items)
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    # For 3+ items, employ the oxford comma.
    return f"{', '.join(items[0:-1])}, and {items[-1]}"


def strip_prefix(string: str, prefix: str) -> str:
    """Returns a copy of the string from which the multi-character prefix has been stripped.

    Use strip_prefix() instead of lstrip() to remove a substring (instead of individual characters)
    from the beginning of a string, if the substring is present.  lstrip() does not match substrings
    but rather treats a substring argument as a set of characters.

    :param string: The string from which to strip the specified prefix.
    :param prefix: The substring to strip from the left of string, if present.
    :return: The string with prefix stripped from the left, if present.
    """
    if string.startswith(prefix):
        return string[len(prefix) :]
    else:
        return string


# NB: We allow bytes because `ProcessResult.std{err,out}` uses bytes.
def strip_v2_chroot_path(v: bytes | str) -> str:
    """Remove all instances of the chroot tmpdir path from the str so that it only uses relative
    paths.

    This is useful when a tool that is run with the V2 engine outputs absolute paths. It is
    confusing for the user to see the absolute path in the final output because it is an
    implementation detail that Pants copies their source code into a chroot.
    """
    if isinstance(v, bytes):
        v = v.decode()
    return re.sub(r"/.*/pants-sandbox-[a-zA-Z0-9]+/", "", v)


@dataclasses.dataclass(frozen=True)
class Simplifier:
    """Helper for options for conditionally simplifying a string."""

    # it's only rarely useful to show a chroot path to a user, hence they're stripped by default
    strip_chroot_path: bool = True
    """remove all instances of the chroot tmpdir path"""
    strip_formatting: bool = False
    """remove ANSI formatting commands (colors, bold, etc)"""

    def simplify(self, v: bytes | str) -> str:
        chroot = (
            strip_v2_chroot_path(v)
            if self.strip_chroot_path
            else v.decode()
            if isinstance(v, bytes)
            else v
        )
        formatting = colors.strip_color(chroot) if self.strip_formatting else chroot
        assert isinstance(formatting, str)

        return formatting


def hard_wrap(s: str, *, indent: int = 0, width: int = 96) -> list[str]:
    """Hard wrap a string while still preserving any prior hard wrapping (new lines).

    This works well when the input uses soft wrapping, e.g. via Python's implicit string
    concatenation.

    Usually, you will want to join the lines together with "\n".join().
    """
    # wrap() returns [] for an empty line, but we want to emit those, hence the `or [line]`.
    return [
        f"{' ' * indent}{wrapped_line}"
        for line in s.splitlines()
        for wrapped_line in textwrap.wrap(line, width=width - indent) or [line]
    ]


def bullet_list(elements: Iterable[str], max_elements: int = -1) -> str:
    """Format a bullet list with padding.

    Callers should normally use `\n\n` before and (if relevant) after this so that the bullets
    appear as a distinct section.

    The `max_elements` may be used to limit the number of bullet rows to output, and instead leave a
    last bullet item with "* ... and N more".
    """
    if not elements:
        return ""

    if max_elements > 0:
        elements = tuple(elements)
        if len(elements) > max_elements:
            elements = elements[: max_elements - 1] + (
                f"... and {len(elements)-max_elements+1} more",
            )

    sep = "\n  * "
    return f"  * {sep.join(elements)}"


def first_paragraph(s: str) -> str:
    """Get the first paragraph, where paragraphs are separated by blank lines."""
    lines = s.splitlines()
    first_blank_line_index = next(
        (i for i, line in enumerate(lines) if line.strip() == ""), len(lines)
    )
    return " ".join(lines[:first_blank_line_index])


# This is more conservative that it necessarily need be. In practice POSIX filesystems
# support any printable character except the path separator (forward slash), but it's
# better to be over-cautious.

# TODO: <> may not be safe in Windows paths. When we support Windows we will probably
#  want to detect that here and be more restrictive on that platform. But we do want
#  to support <> where possible, because they appear in target partition descriptions
#  (e.g., "CPython>=2.7,<3") and those are sometimes converted to paths.
_non_path_safe_re = re.compile(r"[^a-zA-Z0-9_\-.()<>,= ]")


def path_safe(s: str) -> str:
    return _non_path_safe_re.sub("_", s)


# TODO: This may be a bit too eager. Some strings might want to preserve multiple spaces in them
# (e.g. a Python code block which has a comment in it would have 2 spaces before the "#", which
# would be squashed by this eager regex). The challenge is that there's some overlap between prose
# (which shouldn't need multiple spaces) and code (which might) for non-alphanumeric characters.
# We can tighten as necessary.
_super_space_re = re.compile(r"(\S)  +(\S)")
_more_than_2_newlines = re.compile(r"\n{2}\n+")
_leading_whitespace_re = re.compile(r"(^[ ]*)(?:[^ \n])", re.MULTILINE)


def softwrap(text: str) -> str:
    """Turns a multiline-ish string into a softwrapped string.

    This is primarily used to turn strings in source code, which often have a single paragraph
    span multiple source lines, into consistently formatted blocks for hardwrapping later.

    Applies the following rules:
        - Dedents the text (you also don't need to start your string with a backslash)
            (The algorithm used for dedention simply looks at the first indented line and
            unambiguously tries to strip that much indentation from every indented line thereafter.)
        - Replaces all occurrences of multiple spaces in a sentence with a single space
        - Replaces all occurrences of multiple newlines with exactly 2 newlines
        - Replaces singular newlines with a space (to turn a paragraph into one long line)
            - Unless the following line is indented, or begins with a `* ` (to indicate an item in a list),
              in which case the newline and indentation are preserved.
        - Double-newlines are preserved
        - Extra indentation is preserved, and also preserves the indented line's ending
            (If your indented line needs to be continued due to it being longer than the suggested
            width, use trailing backlashes to line-continue the line. Because we squash multiple
            spaces, this will "just work".)

    To keep the numbered or bullet lists indented without converting to a code block,
    make sure to use 2 spaces (and not 4).
    """
    if not text:
        return text
    # If callers didn't use a leading "\" thats OK.
    if text[0] == "\n":
        text = text[1:]

    text = _more_than_2_newlines.sub("\n\n", text)
    margin = _leading_whitespace_re.search(text)
    if margin:
        text = re.sub(r"(?m)^" + margin[1], "", text)

    lines = text.splitlines(keepends=True)
    # NB: collecting a list of strs and `"".join` is more performant than calling `+=` repeatedly.
    result_strs = []
    for i, line in enumerate(lines):
        line = _super_space_re.sub(r"\1 \2", line)
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if (
            "\n" in (line, next_line)
            or line.startswith(" ")
            or next_line.startswith(" ")
            or line.lstrip().startswith("* ")
        ):
            result_strs.append(line)
        else:
            result_strs.append(line.rstrip())
            result_strs.append(" ")

    return "".join(result_strs).rstrip()


_MEMORY_UNITS = ["B", "KiB", "MiB", "GiB"]


def fmt_memory_size(value: int, *, units: Iterable[str] = _MEMORY_UNITS) -> str:
    """Formats a numeric value as amount of bytes alongside the biggest byte-based unit from the
    list that represents the same amount without using decimals."""

    if not units:
        return str(value)

    amount = value
    unit_idx = 0

    units = tuple(units)
    while (amount >= 1024 and amount % 1024 == 0) and unit_idx < len(units) - 1:
        amount = int(amount / 1024)
        unit_idx += 1

    return f"{int(amount)}{units[unit_idx]}"


def strval(val: str | Callable[[], str]) -> str:
    return val if isinstance(val, str) else val()


def help_text(val: str | Callable[[], str]) -> str | Callable[[], str]:
    """Convenience method for defining an optionally lazy-evaluated softwrapped help string.

    This exists because `mypy` does not respect the type hints defined on base `Field` and `Target`
    classes.
    """
    # This can go away when https://github.com/python/mypy/issues/14702 is fixed
    if isinstance(val, str):
        return softwrap(val)
    else:
        return lambda: softwrap(val())  # type: ignore[operator]


P = ParamSpec("P")
R = TypeVar("R")


def docstring(doc: str | Callable[[], str]) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Use this decorator to provide a dynamic doc-string to a function."""

    def wrapper(func: Callable[P, R]) -> Callable[P, R]:
        func.__doc__ = strval(doc)
        return func

    return wrapper


class _JsonEncoder(json.JSONEncoder):
    """Allow us to serialize everything, with a fallback on `str()` in case of any esoteric
    types."""

    def default(self, o):
        """Return a serializable object for o."""
        if isinstance(o, abc.Mapping):
            return dict(o)
        if isinstance(o, (abc.Sequence, OrderedSet, FrozenOrderedSet)):
            return list(o)

        # NB: A quick way to embed the type in the hash so that two objects with the same data but
        # different types produce different hashes.
        classname = o.__class__.__name__
        if dataclasses.is_dataclass(o):
            return {"__class__.__name__": classname, **dataclasses.asdict(o)}
        if isinstance(o, (Digest,)):
            return {"__class__.__name__": classname, "fingerprint": o.fingerprint}
        return super().default(o)


def stable_hash(value: Any, *, name: str = "sha256") -> str:
    """Attempts to return a stable hash of the value stable across processes.

    "Stable" here means that if `value` is equivalent in multiple invocations (across multiple
    processes), it should produce the same hash. To that end, what values are accepted are limited
    in scope.
    """
    return hashlib.new(
        name,
        json.dumps(
            value, indent=None, separators=(",", ":"), sort_keys=True, cls=_JsonEncoder
        ).encode("utf-8"),
    ).hexdigest()
