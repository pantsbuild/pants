# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import os
import re
import shlex
from enum import Enum
from typing import Iterable, Pattern, Sequence

from pants.option.errors import ParseError
from pants.util.eval import parse_expression
from pants.util.memo import memoized_method


class UnsetBool:
    """A type that can be used as the default value for a bool typed option to indicate un-set.

    In other words, `bool`-typed options with a `default=UnsetBool` that are not explicitly set will
    have the value `None`, enabling a tri-state.

    :API: public
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "UnsetBool cannot be instantiated. It should only be used as a " "sentinel type."
        )

    @classmethod
    def coerce_bool(cls, value: type[UnsetBool] | bool | None, default: bool) -> bool:
        if value is None:
            return default
        if value is cls:
            return default
        assert isinstance(value, bool)
        return value


def target_option(s: str) -> str:
    """Same type as 'str', but indicates a single target spec.

    :API: public

    TODO(stuhood): Eagerly convert these to Addresses: see https://rbcommons.com/s/twitter/r/2937/
    """
    return s


def _normalize_directory_separators(s: str) -> str:
    """Coalesce runs of consecutive instances of `os.sep` in `s`, e.g. '//' -> '/' on POSIX.

    The engine will use paths or target addresses either to form globs or to string-match against, and
    including the directory separator '/' multiple times in a row e.g. '//' produces an equivalent
    glob as with a single '/', but produces a different actual string, which will cause the engine to
    fail to glob file paths or target specs correctly.

    TODO: give the engine more control over matching paths so we don't have to sanitize the input!
    """
    return os.path.normpath(s)


def dir_option(s: str) -> str:
    """Same type as 'str', but indicates string represents a directory path.

    :API: public
    """
    return _normalize_directory_separators(s)


def file_option(s: str) -> str:
    """Same type as 'str', but indicates string represents a filepath.

    :API: public
    """
    return _normalize_directory_separators(s)


def dict_with_files_option(s):
    """Same as 'dict', but fingerprints the file contents of any values which are file paths.

    For any value which matches the path of a file on disk, the file path is not fingerprinted -- only
    its contents.

    :API: public
    """
    return DictValueComponent.create(s)


def shell_str(s: str) -> str:
    """A member_type for strings that should be split upon parsing through `shlex.split()`.

    For example, the option value `--foo --bar=val` would be split into `['--foo', '--bar=val']`,
    and then the parser will safely merge this expanded list with any other values defined for the
    option.

    :API: public
    """
    return s


def memory_size(s: str | int | float) -> int:
    """A string that normalizes the suffixes {GiB, MiB, KiB, B} into the number of bytes.

    :API: public
    """
    if isinstance(s, (int, float)):
        return int(s)
    if not s:
        raise ParseError("Missing value.")

    original = s
    s = s.lower().strip()

    try:
        return int(float(s))
    except ValueError:
        pass

    invalid = ParseError(
        f"Invalid value: `{original}`. Expected either a bare number or a number with one of "
        f"`GiB`, `MiB`, `KiB`, or `B`."
    )

    def convert_to_bytes(power_of_2) -> int:
        try:
            return int(float(s[:-3]) * (2 ** power_of_2))  # type: ignore[index]
        except TypeError:
            raise invalid

    if s.endswith("gib"):
        return convert_to_bytes(30)
    elif s.endswith("mib"):
        return convert_to_bytes(20)
    elif s.endswith("kib"):
        return convert_to_bytes(10)
    elif s.endswith("b"):
        try:
            return int(float(s[:-1]))
        except TypeError:
            raise invalid
    raise invalid


def _convert(val, acceptable_types):
    """Ensure that val is one of the acceptable types, converting it if needed.

    :param val: The value we're parsing (either a string or one of the acceptable types).
    :param acceptable_types: A tuple of expected types for val.
    :returns: The parsed value.
    :raises :class:`pants.options.errors.ParseError`: if there was a problem parsing the val as an
                                                      acceptable type.
    """
    if isinstance(val, acceptable_types):
        return val
    return parse_expression(val, acceptable_types, raise_type=ParseError)


def _convert_list(val, member_type, is_enum):
    converted = _convert(val, (list, tuple))
    if not is_enum:
        return converted
    return [item if isinstance(item, member_type) else member_type(item) for item in converted]


def _flatten_shlexed_list(shlexed_args: Sequence[str]) -> list[str]:
    """Convert a list of shlexed args into a flattened list of individual args.

    For example, ['arg1 arg2=foo', '--arg3'] would be converted to ['arg1', 'arg2=foo', '--arg3'].
    """
    return [arg for shlexed_arg in shlexed_args for arg in shlex.split(shlexed_arg)]


class ListValueComponent:
    """A component of the value of a list-typed option.

    One or more instances of this class can be merged to form a list value.

    A component consists of values to append and values to filter while constructing the final list.

    Each component may either replace or modify the preceding component.  So that, e.g., a config
    file can append to and/or filter the default value list, instead of having to repeat most
    of the contents of the default value list.
    """

    REPLACE = "REPLACE"
    MODIFY = "MODIFY"

    # We use a regex to parse the comma-separated lists of modifier expressions (each of which is
    # a list or tuple literal preceded by a + or a -).  Note that these expressions are technically
    # a context-free grammar, but in practice using this regex as a heuristic will work fine. The
    # values that could defeat it are extremely unlikely to be encountered in practice.
    # If we do ever encounter them, we'll have to replace this with a real parser.
    @classmethod
    @memoized_method
    def _get_modifier_expr_re(cls) -> Pattern[str]:
        # Note that the regex consists of a positive lookbehind assertion for a ] or a ),
        # followed by a comma (possibly surrounded by whitespace), followed by a
        # positive lookahead assertion for [ or (.  The lookahead/lookbehind assertions mean that
        # the bracket/paren characters don't get consumed in the split.
        return re.compile(r"(?<=\]|\))\s*,\s*(?=[+-](?:\[|\())")

    @classmethod
    def _split_modifier_expr(cls, s: str) -> list[str]:
        # This check ensures that the first expression (before the first split point) is a modification.
        if s.startswith("+") or s.startswith("-"):
            return cls._get_modifier_expr_re().split(s)
        return [s]

    @classmethod
    def merge(cls, components: Iterable[ListValueComponent]) -> ListValueComponent:
        """Merges components into a single component, applying their actions appropriately.

        This operation is associative:  M(M(a, b), c) == M(a, M(b, c)) == M(a, b, c).
        """
        # Note that action of the merged component is MODIFY until the first REPLACE is encountered.
        # This guarantees associativity.
        action = cls.MODIFY
        appends = []
        filters = []
        for component in components:
            if component._action is cls.REPLACE:
                appends = component._appends
                filters = component._filters
                action = cls.REPLACE
            elif component._action is cls.MODIFY:
                appends.extend(component._appends)
                filters.extend(component._filters)
            else:
                raise ParseError(f"Unknown action for list value: {component._action}")
        return cls(action, appends, filters)

    def __init__(self, action: str, appends: list, filters: list) -> None:
        self._action = action
        self._appends = appends
        self._filters = filters

    @property
    def val(self) -> list:
        ret = list(self._appends)
        for x in self._filters:
            # Note: can't do ret.remove(x) because that only removes the first instance of x.
            ret = [y for y in ret if y != x]
        return ret

    @property
    def action(self):
        return self._action

    @classmethod
    def create(cls, value, member_type=str) -> ListValueComponent:
        """Interpret value as either a list or something to extend another list with.

        Note that we accept tuple literals, but the internal value is always a list.

        :param value: The value to convert.  Can be an instance of ListValueComponent, a list, a tuple,
                      a string representation of a list or tuple (possibly prefixed by + or -
                      indicating modification instead of replacement), or any allowed member_type.
                      May also be a comma-separated sequence of modifications.
        """
        if isinstance(value, cls):  # Ensure idempotency.
            return value

        if isinstance(value, bytes):
            value = value.decode()

        if isinstance(value, str):
            comma_separated_exprs = cls._split_modifier_expr(value)
            if len(comma_separated_exprs) > 1:
                return cls.merge([cls.create(x) for x in comma_separated_exprs])

        action = cls.MODIFY
        appends: Sequence[str] = []
        filters: Sequence[str] = []
        is_enum = inspect.isclass(member_type) and issubclass(member_type, Enum)
        if isinstance(value, (list, tuple)):  # Ensure we can handle list-typed default values.
            action = cls.REPLACE
            appends = value
        elif value.startswith("[") or value.startswith("("):
            action = cls.REPLACE
            appends = _convert_list(value, member_type, is_enum)
        elif value.startswith("+[") or value.startswith("+("):
            appends = _convert_list(value[1:], member_type, is_enum)
        elif value.startswith("-[") or value.startswith("-("):
            filters = _convert_list(value[1:], member_type, is_enum)
        elif is_enum and isinstance(value, str):
            appends = _convert_list([value], member_type, True)
        elif isinstance(value, str):
            appends = [value]
        else:
            appends = _convert(f"[{value}]", list)

        if member_type == shell_str:
            appends = _flatten_shlexed_list(appends)
            filters = _flatten_shlexed_list(filters)

        return cls(action, list(appends), list(filters))

    def __repr__(self) -> str:
        return f"{self._action} +{self._appends} -{self._filters}"


class DictValueComponent:
    """A component of the value of a dict-typed option.

    One or more instances of this class can be merged to form a dict value.

    Each component may either replace or extend the preceding component.  So that, e.g., a config
    file can extend the default value of a dict, instead of having to repeat it.
    """

    REPLACE = "REPLACE"
    EXTEND = "EXTEND"

    @classmethod
    def merge(cls, components: Iterable[DictValueComponent]) -> DictValueComponent:
        """Merges components into a single component, applying their actions appropriately.

        This operation is associative:  M(M(a, b), c) == M(a, M(b, c)) == M(a, b, c).
        """
        # Note that action of the merged component is EXTEND until the first REPLACE is encountered.
        # This guarantees associativity.
        action = cls.EXTEND
        val = {}
        for component in components:
            if component.action is cls.REPLACE:
                val = component.val
                action = cls.REPLACE
            elif component.action is cls.EXTEND:
                val.update(component.val)
            else:
                raise ParseError(f"Unknown action for dict value: {component.action}")
        return cls(action, val)

    def __init__(self, action: str, val: dict) -> None:
        self.action = action
        self.val = val

    @classmethod
    def create(cls, value) -> DictValueComponent:
        """Interpret value as either a dict or something to extend another dict with.

        :param value: The value to convert.  Can be an instance of DictValueComponent, a dict,
                      or a string representation (possibly prefixed by +) of a dict.
        """
        if isinstance(value, bytes):
            value = value.decode()
        if isinstance(value, cls):  # Ensure idempotency.
            action = value.action
            val = value.val
        elif isinstance(value, dict):  # Ensure we can handle dict-typed default values.
            action = cls.REPLACE
            val = value
        elif value.startswith("{"):
            action = cls.REPLACE
            val = _convert(value, dict)
        elif value.startswith("+{"):
            action = cls.EXTEND
            val = _convert(value[1:], dict)
        else:
            raise ParseError(f"Invalid dict value: {value}")
        return cls(action, dict(val))

    def __repr__(self) -> str:
        return f"{self.action} {self.val}"
