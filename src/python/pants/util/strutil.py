# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
import shlex
import textwrap
from typing import Iterable, List, Sequence


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


def safe_shlex_split(text_or_binary: bytes | str) -> List[str]:
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
        path_dirs: List[str] = []
    else:
        path_dirs = list(prev_path.split(delimiter))

    new_entries_list = list(new_entries)

    if prepend:
        path_dirs = new_entries_list + path_dirs
    else:
        path_dirs += new_entries_list

    return delimiter.join(path_dirs)


def pluralize(count: int, item_type: str) -> str:
    """Pluralizes the item_type if the count does not equal one.

    For example `pluralize(1, 'apple')` returns '1 apple',
    while `pluralize(0, 'apple') returns '0 apples'.

    :return The count and inflected item_type together as a string
    """

    def pluralize_string(x: str) -> str:
        if x.endswith("s"):
            return x + "es"
        else:
            return x + "s"

    text = f"{count} {(item_type if count == 1 else pluralize_string(item_type))}"
    return text


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
    return re.sub(r"/.*/process-execution[a-zA-Z0-9]+/", "", v)


def hard_wrap(s: str, *, indent: int = 0, width: int = 96) -> Sequence[str]:
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


def first_paragraph(s: str) -> str:
    """Get the first paragraph, where paragraphs are separated by blank lines."""
    lines = s.splitlines()
    first_blank_line_index = next(
        (i for i, line in enumerate(lines) if line.strip() == ""), len(lines)
    )
    return " ".join(lines[:first_blank_line_index])
