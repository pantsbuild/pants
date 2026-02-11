# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import logging
import shlex
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from pants.base.build_environment import get_buildroot
from pants.engine.fs import FileContent
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import PyConfigSource, PyGoalInfo, PyPantsCommand
from pants.option.custom_types import _flatten_shlexed_list, dir_option, file_option, shell_str
from pants.option.errors import BooleanOptionNameWithNo, OptionsError, ParseError
from pants.option.option_types import OptionInfo
from pants.option.ranked_value import Rank
from pants.option.scope import GLOBAL_SCOPE
from pants.util.strutil import get_strict_env, softwrap

logger = logging.getLogger()


def parse_dest(option_info: OptionInfo) -> str:
    """Return the dest for an option registration.

    If an explicit `dest` is specified, returns that and otherwise derives a default from the
    option flags where '--foo-bar' -> 'foo_bar' and '-x' -> 'x'.

    The dest is used for:
      - The name of the field containing the option value.
      - The key in the config file.
      - Computing the name of the env var used to set the option name.
    """
    dest = option_info.kwargs.get("dest")
    if dest:
        return str(dest)
    # No explicit dest, so compute one based on the first long arg, or the short arg
    # if that's all there is.
    arg = next((a for a in option_info.args if a.startswith("--")), option_info.args[0])
    return arg.lstrip("-").replace("-", "_")


class NativeOptionParser:
    """A Python wrapper around the Rust options parser."""

    int_to_rank = [
        Rank.NONE,
        Rank.HARDCODED,
        Rank.CONFIG_DEFAULT,
        Rank.CONFIG,
        Rank.ENVIRONMENT,
        Rank.FLAG,
    ]

    def __init__(
        self,
        args: Sequence[str] | None,
        env: Mapping[str, str],
        config_sources: Sequence[FileContent] | None,
        allow_pantsrc: bool,
        include_derivation: bool,
        known_scopes_to_flags: dict[str, frozenset[str]],
        known_goals: Sequence[PyGoalInfo],
    ):
        # Remember these args so this object can clone itself in with_derivation() below.
        (
            self._args,
            self._env,
            self._config_sources,
            self._allow_pantsrc,
            self._known_scopes_to_flags,
            self._known_goals,
        ) = (
            args,
            env,
            config_sources,
            allow_pantsrc,
            known_scopes_to_flags,
            known_goals,
        )

        py_config_sources = (
            None
            if config_sources is None
            else [PyConfigSource(cs.path, cs.content) for cs in config_sources]
        )
        self._native_parser = native_engine.PyOptionParser(
            buildroot=None,
            args=args,
            env=dict(get_strict_env(env, logger)),
            configs=py_config_sources,
            allow_pantsrc=allow_pantsrc,
            include_derivation=include_derivation,
            known_scopes_to_flags=known_scopes_to_flags,
            known_goals=known_goals,
        )

        # (type, member_type) -> native get for that type.
        self._getter_by_type = {
            (bool, None): self._native_parser.get_bool,
            (int, None): self._native_parser.get_int,
            (float, None): self._native_parser.get_float,
            (str, None): self._native_parser.get_string,
            (list, bool): self._native_parser.get_bool_list,
            (list, int): self._native_parser.get_int_list,
            (list, float): self._native_parser.get_float_list,
            (list, str): self._native_parser.get_string_list,
            (dict, None): self._native_parser.get_dict,
        }

    def with_derivation(self) -> NativeOptionParser:
        """Return a clone of this object but with value derivation enabled."""
        # We may be able to get rid of this method once we remove the legacy parser entirely.
        # For now it is convenient to allow the help mechanism to get derivations via the
        # existing Options object, which otherwise does not need derivations.
        return NativeOptionParser(
            args=None if self._args is None else tuple(self._args),
            env=dict(self._env),
            config_sources=None if self._config_sources is None else tuple(self._config_sources),
            allow_pantsrc=self._allow_pantsrc,
            include_derivation=True,
            known_scopes_to_flags=self._known_scopes_to_flags,
            known_goals=self._known_goals,
        )

    def get_value(self, *, scope: str, option_info: OptionInfo) -> tuple[Any, Rank]:
        val, rank, _ = self._get_value_and_derivation(scope, option_info)
        return (val, rank)

    def get_derivation(
        self,
        scope: str,
        option_info: OptionInfo,
    ) -> list[tuple[Any, Rank, str | None]]:
        _, _, derivation = self._get_value_and_derivation(scope, option_info)
        return derivation

    def _get_value_and_derivation(
        self,
        scope: str,
        option_info: OptionInfo,
    ) -> tuple[Any, Rank, list[tuple[Any, Rank, str | None]]]:
        return self._get(
            scope=scope,
            dest=parse_dest(option_info),
            flags=option_info.args,
            default=option_info.kwargs.get("default"),
            option_type=option_info.kwargs.get("type"),
            member_type=option_info.kwargs.get("member_type"),
            choices=option_info.kwargs.get("choices"),
            passthrough=option_info.kwargs.get("passthrough"),
        )

    def _get(
        self,
        *,
        scope,
        dest,
        flags,
        default,
        option_type,
        member_type=None,
        choices=None,
        passthrough=False,
    ) -> tuple[Any, Rank, list[tuple[Any, Rank, str | None]]]:
        def scope_str() -> str:
            return "global scope" if scope == GLOBAL_SCOPE else f"scope '{scope}'"

        def is_enum(typ):
            # TODO: When we switch to Python 3.11, use: return isinstance(typ, EnumType)
            return inspect.isclass(typ) and issubclass(typ, Enum)

        def apply_callable(callable_type, val_str):
            try:
                return callable_type(val_str)
            except (TypeError, ValueError) as e:
                if is_enum(callable_type):
                    choices_str = ", ".join(f"{choice.value}" for choice in callable_type)
                    raise ParseError(f"Invalid choice '{val_str}'. Choose from: {choices_str}")
                raise ParseError(
                    f"Error applying type '{callable_type.__name__}' to option value '{val_str}': {e}"
                )

        # '--foo.bar-baz' -> ['foo', 'bar', 'baz']
        name_parts = flags[-1][2:].replace(".", "-").split("-")
        switch = flags[0][1:] if len(flags) > 1 else None  # '-d' -> 'd'
        option_id = native_engine.PyOptionId(*name_parts, scope=scope or "GLOBAL", switch=switch)

        rust_option_type = option_type
        rust_member_type = member_type

        if option_type is bool:
            if name_parts[0] == "no":
                raise BooleanOptionNameWithNo(scope, dest)
        elif option_type is dict:
            # The Python code allows registering default=None for dicts/lists, and forces it to
            # an empty dict/list at registration. Since here we only have access to what the user
            # provided, we do the same.
            if default is None:
                default = {}
            elif isinstance(default, str):
                default = eval(default)
        elif option_type is list:
            if default is None:
                default = []
            if member_type is None:
                member_type = rust_member_type = str

            if member_type == shell_str:
                rust_member_type = str
                if isinstance(default, str):
                    default = shlex.split(default)
            elif is_enum(member_type):
                rust_member_type = str
                default = [x.value for x in default]
            elif inspect.isfunction(rust_member_type):
                rust_member_type = str
            elif rust_member_type != str and isinstance(default, str):
                default = eval(default)
        elif is_enum(option_type):
            if default is not None:
                default = default.value
                rust_option_type = type(default)
            else:
                rust_option_type = str
        elif option_type not in {bool, int, float, str}:
            # For enum and other specialized types.
            rust_option_type = str
            if default is not None:
                default = str(default)

        getter = self._getter_by_type.get((rust_option_type, rust_member_type))
        if getter is None:
            suffix = f" with member type {rust_member_type}" if rust_option_type is list else ""
            raise OptionsError(f"Unsupported type: {rust_option_type}{suffix}")

        val, rank_int, derivation = getter(option_id, default)  # type:ignore
        rank = self.int_to_rank[rank_int]

        def process_value(v):
            if option_type is list:
                if member_type == shell_str:
                    v = _flatten_shlexed_list(v)
                elif callable(member_type):
                    v = [apply_callable(member_type, x) for x in v]
                if passthrough:
                    v += self._native_parser.get_command().passthru() or []
            elif callable(option_type):
                v = apply_callable(option_type, v)
            return v

        if derivation:
            derivation = [(process_value(v), self.int_to_rank[r], d) for (v, r, d) in derivation]

        if val is not None:
            val = process_value(val)

            # Validate the value.

            def check_scalar_value(val, choices):
                if choices is None and is_enum(option_type):
                    choices = list(option_type)
                if choices is not None and val not in choices:
                    raise ParseError(
                        softwrap(
                            f"""
                            `{val}` is not an allowed value for option {dest} in {scope_str()}.
                            Must be one of: {choices}
                            """
                        )
                    )
                elif option_type == file_option:
                    check_file_exists(val, dest, scope_str())
                elif option_type == dir_option:
                    check_dir_exists(val, dest, scope_str())

            if isinstance(val, list):
                for component in val:
                    check_scalar_value(component, choices)
                if is_enum(member_type) and len(val) != len(set(val)):
                    raise ParseError(f"Duplicate enum values specified in list: {val}")
            elif isinstance(val, dict):
                for component in val.values():
                    check_scalar_value(component, choices)
            else:
                check_scalar_value(val, choices)

        return (val, rank, derivation)

    def get_command(self) -> PyPantsCommand:
        return self._native_parser.get_command()

    def get_unconsumed_flags(self) -> dict[str, tuple[str, ...]]:
        return {k: tuple(v) for k, v in self._native_parser.get_unconsumed_flags().items()}

    def validate_config(self, valid_keys: dict[str, set[str]]) -> list[str]:
        return self._native_parser.validate_config(valid_keys)


def check_file_exists(val: str, dest: str, scope: str) -> None:
    error_prefix = f"File value `{val}` for option `{dest}` in `{scope}`"
    try:
        path = Path(val)
        path_with_buildroot = Path(get_buildroot(), val)
    except TypeError:
        raise ParseError(f"{error_prefix} cannot be parsed as a file path.")
    if not path.is_file() and not path_with_buildroot.is_file():
        raise ParseError(f"{error_prefix} does not exist.")


def check_dir_exists(val: str, dest: str, scope: str) -> None:
    error_prefix = f"Directory value `{val}` for option `{dest}` in `{scope}`"
    try:
        path = Path(val)
        path_with_buildroot = Path(get_buildroot(), val)
    except TypeError:
        raise ParseError(f"{error_prefix} cannot be parsed as a directory path.")
    if not path.is_dir() and not path_with_buildroot.is_dir():
        raise ParseError(f"{error_prefix} does not exist.")
