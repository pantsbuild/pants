# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import configparser
import getpass
import itertools
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from hashlib import sha1
from typing import Any, ClassVar, Dict, Iterable, List, Mapping, Sequence, Union, cast

import toml
from typing_extensions import Protocol

from pants.base.build_environment import get_buildroot
from pants.option.ranked_value import Value
from pants.util.eval import parse_expression
from pants.util.ordered_set import OrderedSet

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


class Config(ABC):
    """Encapsulates config file loading and access, including encapsulation of support for multiple
    config files.

    Supports variable substitution using old-style Python format strings. E.g., %(var_name)s will be
    replaced with the value of var_name.
    """

    DEFAULT_SECTION: ClassVar[str] = configparser.DEFAULTSECT

    class ConfigError(Exception):
        pass

    class ConfigValidationError(ConfigError):
        pass

    @classmethod
    def load(
        cls,
        file_contents: Iterable[ConfigSource],
        *,
        seed_values: SeedValues | None = None,
    ) -> Config:
        """Loads config from the given string payloads, with later payloads overriding earlier ones.

        A handful of seed values will be set to act as if specified in the loaded config file's
        DEFAULT section, and be available for use in substitutions.  The caller may override some of
        these seed values.
        """
        single_file_configs = []
        for file_content in file_contents:
            content_digest = sha1(file_content.content).hexdigest()
            normalized_seed_values = cls._determine_seed_values(seed_values=seed_values)

            try:
                config_values = cls._parse_toml(
                    file_content.content.decode(), normalized_seed_values
                )
            except Exception as e:
                raise cls.ConfigError(
                    f"Config file {file_content.path} could not be parsed as TOML:\n  {e}"
                )

            single_file_configs.append(
                _SingleFileConfig(
                    config_path=file_content.path,
                    content_digest=content_digest,
                    values=config_values,
                ),
            )
        return _ChainedConfig(tuple(reversed(single_file_configs)))

    @classmethod
    def _parse_toml(
        cls, config_content: str, normalized_seed_values: dict[str, str]
    ) -> _ConfigValues:
        """Attempt to parse as TOML, raising an exception on failure."""
        toml_values = cast(Dict[str, Any], toml.loads(config_content))
        toml_values["DEFAULT"] = {
            **normalized_seed_values,
            **toml_values.get("DEFAULT", {}),
        }
        return _ConfigValues(toml_values)

    @staticmethod
    def _determine_seed_values(*, seed_values: SeedValues | None = None) -> dict[str, str]:
        """We pre-populate several default values to allow %([key-name])s interpolation.

        This sets up those defaults and checks if the user overrode any of the values.
        """
        safe_seed_values = seed_values or {}
        buildroot = cast(str, safe_seed_values.get("buildroot", get_buildroot()))

        all_seed_values: dict[str, str] = {
            "buildroot": buildroot,
            "homedir": os.path.expanduser("~"),
            "user": getpass.getuser(),
        }

        def update_seed_values(key: str, *, default_dir: str) -> None:
            all_seed_values[key] = cast(
                str, safe_seed_values.get(key, os.path.join(buildroot, default_dir))
            )

        update_seed_values("pants_workdir", default_dir=".pants.d")
        update_seed_values("pants_distdir", default_dir="dist")

        return all_seed_values

    def get(self, section, option, type_=str, default=None):
        """Retrieves option from the specified section (or 'DEFAULT') and attempts to parse it as
        type.

        If the specified section does not exist or is missing a definition for the option, the value
        is looked up in the DEFAULT section.  If there is still no definition found, the default
        value supplied is returned.
        """
        if not self.has_option(section, option):
            return default

        raw_value = self.get_value(section, option)
        if issubclass(type_, str):
            return raw_value

        key = f"{section}.{option}"
        return parse_expression(
            name=key, val=raw_value, acceptable_types=type_, raise_type=self.ConfigError
        )

    @abstractmethod
    def configs(self) -> Sequence[_SingleFileConfig]:
        """Returns the underlying single-file configs represented by this object."""

    @abstractmethod
    def sources(self) -> list[str]:
        """Returns the sources of this config as a list of filenames."""

    @abstractmethod
    def sections(self) -> list[str]:
        """Returns the sections in this config (not including DEFAULT)."""

    @abstractmethod
    def has_section(self, section: str) -> bool:
        """Returns whether this config has the section."""

    @abstractmethod
    def has_option(self, section: str, option: str) -> bool:
        """Returns whether this config specified a value for the option."""

    @abstractmethod
    def get_value(self, section: str, option: str) -> str | None:
        """Returns the value of the option in this config as a string, or None if no value
        specified."""

    @abstractmethod
    def get_source_for_option(self, section: str, option: str) -> str | None:
        """Returns the path to the source file the given option was defined in.

        :param section: the scope of the option.
        :param option: the name of the option.
        :returns: the path to the config file, or None if the option was not defined by a config file.
        """


_TomlPrimitive = Union[bool, int, float, str]
_TomlValue = Union[_TomlPrimitive, List[_TomlPrimitive]]


@dataclass(frozen=True)
class _ConfigValues:
    """The parsed contents of a TOML config file."""

    values: dict[str, Any]

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
                pattern=r"%\((?P<interpolated>[a-zA-Z_0-9]*)\)s",
                repl=r"{\g<interpolated>}",
                string=escaped_str,
            )
            try:
                possible_interpolations = {**self.defaults, **section_values}
                return new_style_format_str.format(**possible_interpolations)
            except KeyError as e:
                bad_reference = e.args[0]
                raise configparser.InterpolationMissingOptionError(
                    option,
                    section,
                    raw_value,
                    bad_reference,
                )

        def recursively_format_str(value: str) -> str:
            # It's possible to interpolate with a value that itself has an interpolation. We must
            # fully evaluate all expressions for parity with configparser.
            match = re.search(r"%\(([a-zA-Z_0-9]*)\)s", value)
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
        """For parity with configparser, we convert all values back to strings, which allows us to
        avoid upstream changes to files like parser.py.

        This is clunky. If we drop INI support, we should remove this and use native values
        (although we must still support interpolation).
        """
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

    @property
    def sections(self) -> list[str]:
        return [scope for scope in self.values if scope != "DEFAULT"]

    def has_section(self, section: str) -> bool:
        return section in self.values

    def has_option(self, section: str, option: str) -> bool:
        if not self.has_section(section):
            return False
        return option in self.values[section] or option in self.defaults

    def get_value(self, section: str, option: str) -> str | None:
        section_values = self.values.get(section)
        if section_values is None:
            raise configparser.NoSectionError(section)

        stringify = partial(
            self._stringify_val,
            option=option,
            section=section,
            section_values=section_values,
        )

        if option not in section_values:
            if option in self.defaults:
                return stringify(raw_value=self.defaults[option])
            raise configparser.NoOptionError(option, section)

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

        add_val = stringify(option_value["add"], list_prefix="+") if has_add else None
        remove_val = stringify(option_value["remove"], list_prefix="-") if has_remove else None
        if has_add and has_remove:
            return f"{add_val},{remove_val}"
        if has_add:
            return add_val
        return remove_val

    def options(self, section: str) -> list[str]:
        section_values = self.values.get(section)
        if section_values is None:
            raise configparser.NoSectionError(section)
        return [
            *section_values.keys(),
            *(
                default_option
                for default_option in self.defaults
                if default_option not in section_values
            ),
        ]

    @property
    def defaults(self) -> dict[str, str]:
        return {
            option: self._stringify_val_without_interpolation(option_val)
            for option, option_val in self.values["DEFAULT"].items()
        }


@dataclass(frozen=True, eq=False)
class _SingleFileConfig(Config):
    """Config read from a single file."""

    config_path: str
    content_digest: str
    values: _ConfigValues

    def configs(self) -> list[_SingleFileConfig]:
        return [self]

    def sources(self) -> list[str]:
        return [self.config_path]

    def sections(self) -> list[str]:
        return self.values.sections

    def has_section(self, section: str) -> bool:
        return self.values.has_section(section)

    def has_option(self, section: str, option: str) -> bool:
        return self.values.has_option(section, option)

    def get_value(self, section: str, option: str) -> str | None:
        return self.values.get_value(section, option)

    def get_source_for_option(self, section: str, option: str) -> str | None:
        if self.has_option(section, option):
            return self.sources()[0]
        return None

    def __repr__(self) -> str:
        return f"SingleFileConfig({self.config_path})"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, _SingleFileConfig):
            return NotImplemented
        return self.config_path == other.config_path and self.content_digest == other.content_digest

    def __hash__(self) -> int:
        return hash(self.content_digest)


@dataclass(frozen=True)
class _ChainedConfig(Config):
    """Config read from multiple sources."""

    # Config instances to chain. Later instances take precedence over earlier ones.
    chained_configs: tuple[_SingleFileConfig, ...]

    @property
    def _configs(self) -> tuple[_SingleFileConfig, ...]:
        return self.chained_configs

    def configs(self) -> tuple[_SingleFileConfig, ...]:
        return self.chained_configs

    def sources(self) -> list[str]:
        # NB: Present the sources in the order we were given them.
        return list(itertools.chain.from_iterable(cfg.sources() for cfg in reversed(self._configs)))

    def sections(self) -> list[str]:
        ret: OrderedSet[str] = OrderedSet()
        for cfg in self._configs:
            ret.update(cfg.sections())
        return list(ret)

    def has_section(self, section: str) -> bool:
        for cfg in self._configs:
            if cfg.has_section(section):
                return True
        return False

    def has_option(self, section: str, option: str) -> bool:
        for cfg in self._configs:
            if cfg.has_option(section, option):
                return True
        return False

    def get_value(self, section: str, option: str) -> str | None:
        for cfg in self._configs:
            try:
                return cfg.get_value(section, option)
            except (configparser.NoSectionError, configparser.NoOptionError):
                pass
        if not self.has_section(section):
            raise configparser.NoSectionError(section)
        raise configparser.NoOptionError(option, section)

    def get_source_for_option(self, section: str, option: str) -> str | None:
        for cfg in self._configs:
            if cfg.has_option(section, option):
                return cfg.get_source_for_option(section, option)
        return None

    def __repr__(self) -> str:
        return f"ChainedConfig({self.sources()})"


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
