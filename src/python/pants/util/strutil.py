# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import shlex
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union


def ensure_binary(text_or_binary: Union[bytes, str]) -> bytes:
    if isinstance(text_or_binary, bytes):
        return text_or_binary
    elif isinstance(text_or_binary, str):
        return text_or_binary.encode("utf8")
    else:
        raise TypeError(f"Argument is neither text nor binary type.({type(text_or_binary)})")


def ensure_text(text_or_binary: Union[bytes, str]) -> str:
    if isinstance(text_or_binary, bytes):
        return text_or_binary.decode()
    elif isinstance(text_or_binary, str):
        return text_or_binary
    else:
        raise TypeError(f"Argument is neither text nor binary type ({type(text_or_binary)})")


def is_text_or_binary(obj: Any) -> bool:
    return isinstance(obj, (str, bytes))


def safe_shlex_split(text_or_binary: Union[bytes, str]) -> List[str]:
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
    new_entries: Sequence[str],
    env: Optional[Dict[str, str]] = None,
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


def module_dirname(module_path: str) -> str:
    """Return the import path for the parent module of `module_path`."""
    return ".".join(module_path.split(".")[:-1])


def camelcase(string: str) -> str:
    """Convert snake casing (containing - or _ characters) to camel casing."""
    return "".join(word.capitalize() for word in re.split("[-_]", string))


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
