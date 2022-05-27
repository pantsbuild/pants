# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import getpass
import logging
import os
import re
from dataclasses import dataclass
from functools import partial
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Union, cast

import toml
from typing_extensions import Protocol

from pants.base.build_environment import get_buildroot
from pants.option.errors import ConfigError, ConfigValidationError, InterpolationMissingOptionError
from pants.option.ranked_value import Value

logger = logging.getLogger(__name__)


# A dict with optional override seed values for buildroot, pants_workdir, and pants_distdir.
SeedValues = Dict[str, Value]


class ConfigSource(Protocol):
    """A protocol that matches pants.engine.fs.FileContent.

    Also matches the ad-hoc FileContent-like class we use during options bootstrapping, where we
    cannot use pants.engine.fs.FileContent itself due to circular imports.
    """

    @property
    def path(self) -> str:
        raise NotImplementedError()

    @property
    def content(self) -> bytes:
        raise NotImplementedError()


DEFAULT_SECTION = "DEFAULT"


@dataclass(frozen=True, eq=False)
class Config:
    """Encapsulates config file loading and access, including encapsulation of support for multiple
    config files.

    Supports variable substitution using old-style Python format strings. E.g., %(var_name)s will be
    replaced with the value of var_name.
    """

    values: tuple[_ConfigValues, ...]

    @classmethod
    def load(
        cls,
        file_contents: Iterable[ConfigSource],
        *,
        seed_values: SeedValues | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Config:
        """Loads config from the given string payloads, with later payloads overriding earlier ones.

        A handful of seed values will be set to act as if specified in the loaded config file's
        DEFAULT section, and be available for use in substitutions.  The caller may override some of
        these seed values.

        If an `env` is supplied, it is exposed as `env` object available for interpolation via dot
        access of the environment variable names (e.g.: `env.HOME`).
        """
        config_values = []
        for file_content in file_contents:
            normalized_seed_values = cls._determine_seed_values(seed_values=seed_values, env=env)
            try:
                config_values.append(cls._parse_toml(file_content, normalized_seed_values))
            except Exception as e:
                raise ConfigError(
                    f"Config file {file_content.path} could not be parsed as TOML:\n  {e}"
                )
        return cls(tuple(config_values))

    @classmethod
    def _parse_toml(
        cls, config_source: ConfigSource, normalized_seed_values: dict[str, Any]
    ) -> _ConfigValues:
        """Attempt to parse as TOML, raising an exception on failure."""
        toml_values = cast(Dict[str, Any], toml.loads(config_source.content.decode()))
        toml_values[DEFAULT_SECTION] = {
            **normalized_seed_values,
            **toml_values.get(DEFAULT_SECTION, {}),
        }
        return _ConfigValues(config_source.path, toml_values)

    def verify(self, section_to_valid_options: dict[str, set[str]]):
        error_log = []
        for config_values in self.values:
            error_log.extend(config_values.get_verification_errors(section_to_valid_options))
        if error_log:
            for error in error_log:
                logger.error(error)
            raise ConfigValidationError(
                "Invalid config entries detected. See log for details on which entries to update "
                "or remove.\n(Specify --no-verify-config to disable this check.)"
            )

    @staticmethod
    def _determine_seed_values(
        *, seed_values: SeedValues | None = None, env: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        """We pre-populate several default values to allow %([key-name])s interpolation.

        This sets up those defaults and checks if the user overrode any of the values.

        In addition, we pre-populate any supplied env entries to allow %(env.[env-var-name])s
        interpolation.
        """
        safe_seed_values = seed_values or {}
        buildroot = cast(str, safe_seed_values.get("buildroot", get_buildroot()))

        all_seed_values: dict[str, Any] = {
            "buildroot": buildroot,
            "homedir": os.path.expanduser("~"),
            "user": getpass.getuser(),
        }
        if env:
            all_seed_values["env"] = SimpleNamespace(**env)

        def update_seed_values(key: str, *, default_dir: str) -> None:
            all_seed_values[key] = cast(
                str, safe_seed_values.get(key, os.path.join(buildroot, default_dir))
            )

        update_seed_values("pants_workdir", default_dir=".pants.d")
        update_seed_values("pants_distdir", default_dir="dist")

        return all_seed_values

    def get(self, section, option) -> list[str]:
        """Retrieves an option value from each config file in which it appears."""
        available_vals = []
        for vals in self.values:
            val = vals.get_value(section, option)
            if val is not None:
                available_vals.append(val)
        return available_vals

    def sources(self) -> list[str]:
        """Returns the sources of this config as a list of filenames."""
        return [vals.path for vals in self.values]

    def get_sources_for_option(self, section: str, option: str) -> list[str]:
        """Returns the path(s) to the source file(s) the given option was defined in."""
        paths = []
        for vals in reversed(self.values):
            if vals.get_value(section, option) is not None:
                paths.append(os.path.relpath(vals.path))
        return paths


_TomlPrimitive = Union[bool, int, float, str]
_TomlValue = Union[_TomlPrimitive, List[_TomlPrimitive]]


@dataclass(frozen=True)
class _ConfigValues:
    """The parsed contents of a TOML config file."""

    path: str
    section_to_values: dict[str, dict[str, Any]]

    @staticmethod
    def _is_an_option(option_value: _TomlValue | dict) -> bool:
        """Determine if the value is actually an option belonging to that section.

        This handles the special syntax of `my_list_option.add` and `my_list_option.remove`.
        """
        if isinstance(option_value, dict):
            return "add" in option_value or "remove" in option_value
        return True

    def _possibly_interpolate_value(
        self,
        raw_value: str,
        *,
        option: str,
        section: str,
        section_values: dict,
    ) -> str:
        """For any values with %(foo)s, substitute it with the corresponding value from DEFAULT or
        the same section."""

        def format_str(value: str) -> str:
            # Because dictionaries use the symbols `{}`, we must proactively escape the symbols so
            # that .format() does not try to improperly interpolate.
            escaped_str = value.replace("{", "{{").replace("}", "}}")
            new_style_format_str = re.sub(
                pattern=r"%\((?P<interpolated>[a-zA-Z_0-9.]+)\)s",
                repl=r"{\g<interpolated>}",
                string=escaped_str,
            )
            try:
                possible_interpolations = {**self.defaults, **section_values}
                return new_style_format_str.format(**possible_interpolations)
            except KeyError as e:
                bad_reference = e.args[0]
                raise InterpolationMissingOptionError(
                    option,
                    section,
                    raw_value,
                    bad_reference,
                )

        def recursively_format_str(value: str) -> str:
            # It's possible to interpolate with a value that itself has an interpolation.
            match = re.search(r"%\(([a-zA-Z_0-9.]+)\)s", value)
            if not match:
                return value
            return recursively_format_str(value=format_str(value))

        return recursively_format_str(raw_value)

    def _stringify_val(
        self,
        raw_value: _TomlValue,
        *,
        option: str,
        section: str,
        section_values: dict,
        interpolate: bool = True,
        list_prefix: str | None = None,
    ) -> str:
        # We convert all values to strings, which allows us to treat them uniformly with
        # env vars and cmd-line flags in parser.py.
        possibly_interpolate = partial(
            self._possibly_interpolate_value,
            option=option,
            section=section,
            section_values=section_values,
        )
        if isinstance(raw_value, str):
            return possibly_interpolate(raw_value) if interpolate else raw_value

        if isinstance(raw_value, list):

            def stringify_list_member(member: _TomlPrimitive) -> str:
                if not isinstance(member, str):
                    return str(member)
                interpolated_member = possibly_interpolate(member) if interpolate else member
                return f'"{interpolated_member}"'

            list_members = ", ".join(stringify_list_member(member) for member in raw_value)
            return f"{list_prefix or ''}[{list_members}]"

        return str(raw_value)

    def _stringify_val_without_interpolation(self, raw_value: _TomlValue) -> str:
        return self._stringify_val(
            raw_value,
            option="",
            section="",
            section_values={},
            interpolate=False,
        )

    def get_value(self, section: str, option: str) -> str | None:
        section_values = self.section_to_values.get(section)
        if section_values is None:
            return None
        if option not in section_values:
            return None

        stringify = partial(
            self._stringify_val,
            option=option,
            section=section,
            section_values=section_values,
        )

        option_value = section_values[option]
        if not isinstance(option_value, dict):
            return stringify(option_value)

        # Handle dict options, along with the special `my_list_option.add` and
        # `my_list_option.remove` syntax. We only treat `add` and `remove` as the special list
        # syntax if the values are lists to reduce the risk of incorrectly special casing.
        has_add = isinstance(option_value.get("add"), list)
        has_remove = isinstance(option_value.get("remove"), list)
        if not has_add and not has_remove:
            return stringify(option_value)

        add_val = stringify(option_value["add"], list_prefix="+") if has_add else "[]"
        remove_val = stringify(option_value["remove"], list_prefix="-") if has_remove else "[]"
        if has_add and has_remove:
            return f"{add_val},{remove_val}"
        if has_add:
            return add_val
        return remove_val

    @property
    def defaults(self) -> dict[str, Any]:
        return self.section_to_values[DEFAULT_SECTION].copy()

    def get_verification_errors(self, section_to_valid_options: dict[str, set[str]]) -> list[str]:
        error_log = []
        for section, vals in self.section_to_values.items():
            if section == DEFAULT_SECTION:
                continue
            try:
                valid_options_in_section = section_to_valid_options[section]
            except KeyError:
                error_log.append(f"Invalid section [{section}] in {self.path}")
            else:
                for option in sorted(set(vals.keys()) - valid_options_in_section):
                    if option not in valid_options_in_section:
                        error_log.append(
                            f"Invalid option '{option}' under [{section}] in {self.path}"
                        )
        return error_log


@dataclass(frozen=True)
class TomlSerializer:
    """Convert a dictionary of option scopes -> Python values into TOML understood by Pants.

    The constructor expects a dictionary of option scopes to their corresponding values as
    represented in Python. For example:

      {
        "GLOBAL": {
          "o1": True,
          "o2": "hello",
          "o3": [0, 1, 2],
        },
        "some-subsystem": {
          "dict_option": {
            "a": 0,
            "b": 0,
          },
        },
      }
    """

    parsed: Mapping[str, dict[str, int | float | str | bool | list | dict]]

    def normalize(self) -> dict:
        def normalize_section_value(option, option_value) -> tuple[str, Any]:
            # With TOML, we store dict values as strings (for now).
            if isinstance(option_value, dict):
                option_value = str(option_value)
            if option.endswith(".add"):
                option = option.rsplit(".", 1)[0]
                option_value = f"+{option_value!r}"
            elif option.endswith(".remove"):
                option = option.rsplit(".", 1)[0]
                option_value = f"-{option_value!r}"
            return option, option_value

        return {
            section: dict(
                normalize_section_value(option, option_value)
                for option, option_value in section_values.items()
            )
            for section, section_values in self.parsed.items()
        }

    def serialize(self) -> str:
        toml_values = self.normalize()
        return toml.dumps(toml_values)
