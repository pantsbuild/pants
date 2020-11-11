# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import getpass
import io
import itertools
import os
import re
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from hashlib import sha1
from pathlib import PurePath
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple, Union, cast

import toml
from typing_extensions import Literal

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.option.ranked_value import Value
from pants.util.eval import parse_expression
from pants.util.ordered_set import OrderedSet

# A dict with optional override seed values for buildroot, pants_workdir, pants_supportdir and
# pants_distdir.
SeedValues = Dict[str, Value]


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
    def load_file_contents(
        cls,
        file_contents,
        *,
        seed_values: Optional[SeedValues] = None,
    ) -> Union["_EmptyConfig", "_ChainedConfig"]:
        """Loads config from the given string payloads, with later payloads taking precedence over
        earlier ones.

        A handful of seed values will be set to act as if specified in the loaded config file's
        DEFAULT section, and be available for use in substitutions.  The caller may override some of
        these seed values.
        """

        @contextmanager
        def opener(file_content):
            with io.BytesIO(file_content.content) as fh:
                yield fh

        return cls._meta_load(opener, file_contents, seed_values=seed_values)

    @classmethod
    def load(
        cls,
        config_paths: List[str],
        *,
        seed_values: Optional[SeedValues] = None,
    ) -> Union["_EmptyConfig", "_ChainedConfig"]:
        """Loads config from the given paths, with later paths taking precedence over earlier ones.

        A handful of seed values will be set to act as if specified in the loaded config file's
        DEFAULT section, and be available for use in substitutions.  The caller may override some of
        these seed values.
        """

        @contextmanager
        def opener(f):
            with open(f, "rb") as fh:
                yield fh

        return cls._meta_load(opener, config_paths, seed_values=seed_values)

    @classmethod
    def _meta_load(
        cls,
        open_ctx,
        config_items: Sequence,
        *,
        seed_values: Optional[SeedValues] = None,
    ) -> Union["_EmptyConfig", "_ChainedConfig"]:
        if not config_items:
            return _EmptyConfig()

        single_file_configs = []
        for config_item in config_items:
            config_path = config_item.path if hasattr(config_item, "path") else config_item
            with open_ctx(config_item) as config_file:
                content_bytes = config_file.read()
            content_digest = sha1(content_bytes).hexdigest()
            content = content_bytes.decode()
            normalized_seed_values = cls._determine_seed_values(seed_values=seed_values)

            if PurePath(config_path).suffix == ".toml":
                config_values = cls._parse_toml(content, normalized_seed_values)
            else:
                try:
                    config_values = cls._parse_toml(content, normalized_seed_values)
                except Exception as e:
                    raise cls.ConfigError(
                        f"Unsuffixed Config path {config_path} could not be parsed "
                        f"as TOML:\n  {e}"
                    )

            single_file_configs.append(
                _SingleFileConfig(
                    config_path=config_path,
                    content_digest=content_digest,
                    values=config_values,
                ),
            )
        return _ChainedConfig(tuple(reversed(single_file_configs)))

    @classmethod
    def _parse_toml(
        cls, config_content: str, normalized_seed_values: Dict[str, str]
    ) -> "_ConfigValues":
        """Attempt to parse as TOML, raising an exception on failure."""
        toml_values = cast(Dict[str, Any], toml.loads(config_content))
        toml_values["DEFAULT"] = {
            **normalized_seed_values,
            **toml_values.get("DEFAULT", {}),
        }
        return _ConfigValues(toml_values)

    @staticmethod
    def _determine_seed_values(*, seed_values: Optional[SeedValues] = None) -> Dict[str, str]:
        """We pre-populate several default values to allow %([key-name])s interpolation.

        This sets up those defaults and checks if the user overrode any of the values.
        """
        safe_seed_values = seed_values or {}
        buildroot = cast(str, safe_seed_values.get("buildroot", get_buildroot()))

        all_seed_values: Dict[str, str] = {
            "buildroot": buildroot,
            "homedir": os.path.expanduser("~"),
            "user": getpass.getuser(),
            "pants_bootstrapdir": get_pants_cachedir(),
            "pants_configdir": get_pants_configdir(),
        }

        def update_seed_values(key: str, *, default_dir: str) -> None:
            all_seed_values[key] = cast(
                str, safe_seed_values.get(key, os.path.join(buildroot, default_dir))
            )

        update_seed_values("pants_workdir", default_dir=".pants.d")
        update_seed_values("pants_supportdir", default_dir="build-support")
        update_seed_values("pants_distdir", default_dir="dist")

        return all_seed_values

    def get(self, section, option, type_=str, default=None):
        """Retrieves option from the specified section (or 'DEFAULT') and attempts to parse it as
        type.

        If the specified section does not exist or is missing a definition for the option, the value
        is looked up in the DEFAULT section.  If there is still no definition found, the default
        value supplied is returned.
        """
        return self._getinstance(section, option, type_, default)

    def _getinstance(self, section, option, type_, default=None):
        if not self.has_option(section, option):
            return default

        raw_value = self.get_value(section, option)
        if type_ == str or issubclass(type_, str):
            return raw_value

        key = f"{section}.{option}"
        return parse_expression(
            name=key, val=raw_value, acceptable_types=type_, raise_type=self.ConfigError
        )

    @abstractmethod
    def configs(self) -> Sequence["_SingleFileConfig"]:
        """Returns the underlying single-file configs represented by this object."""

    @abstractmethod
    def sources(self) -> List[str]:
        """Returns the sources of this config as a list of filenames."""

    @abstractmethod
    def sections(self) -> List[str]:
        """Returns the sections in this config (not including DEFAULT)."""

    @abstractmethod
    def has_section(self, section: str) -> bool:
        """Returns whether this config has the section."""

    @abstractmethod
    def has_option(self, section: str, option: str) -> bool:
        """Returns whether this config specified a value for the option."""

    @abstractmethod
    def get_value(self, section: str, option: str) -> Optional[str]:
        """Returns the value of the option in this config as a string, or None if no value
        specified."""

    @abstractmethod
    def get_source_for_option(self, section: str, option: str) -> Optional[str]:
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

    values: Dict[str, Any]

    @staticmethod
    def _is_an_option(option_value: Union[_TomlValue, Dict]) -> bool:
        """Determine if the value is actually an option belonging to that section.

        A value that looks like an option might actually be a subscope, e.g. the option value
        `java` belonging to the section `cache` could actually be the section `cache.java`, rather
        than the option `--cache-java`.

        We must also handle the special syntax of `my_list_option.add` and `my_list_option.remove`.
        """
        if isinstance(option_value, dict):
            return "add" in option_value or "remove" in option_value
        return True

    @staticmethod
    def _section_explicitly_defined(section_values: Dict) -> bool:
        """Determine if the section is truly a defined section, meaning that the user explicitly
        wrote the section in their config file.

        For example, the user may have explicitly defined `cache.java` but never defined `cache`.
        Due to TOML's representation of the config as a nested dictionary, naively, it would appear
        that `cache` was defined even though the user never explicitly added it to their config.
        """
        at_least_one_option_defined = any(
            _ConfigValues._is_an_option(section_value) for section_value in section_values.values()
        )
        # We also check if the section was explicitly defined but has no options. We can be
        # confident that this is not a parent scope (e.g. `cache` when `cache.java` is really what
        # was defined) because the parent scope would store its child scope in its values, so the
        # values would not be empty.
        blank_section = len(section_values.values()) == 0
        return at_least_one_option_defined or blank_section

    def _find_section_values(self, section: str) -> Optional[Dict]:
        """Find the values for a section, if any.

        For example, if the config file was `{'GLOBAL': {'foo': 1}}`, this function would return
        `{'foo': 1}` given `section='GLOBAL'`.
        """

        def recurse(mapping: Dict, *, remaining_sections: List[str]) -> Optional[Dict]:
            if not remaining_sections:
                return None
            current_section = remaining_sections[0]
            if current_section not in mapping:
                return None
            section_values = mapping[current_section]
            if len(remaining_sections) > 1:
                return recurse(section_values, remaining_sections=remaining_sections[1:])
            if not self._section_explicitly_defined(section_values):
                return None
            return cast(Dict, section_values)

        return recurse(mapping=self.values, remaining_sections=section.split("."))

    def _possibly_interpolate_value(
        self,
        raw_value: str,
        *,
        option: str,
        section: str,
        section_values: Dict,
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
            if not re.search(r"%\([a-zA-Z_0-9]*\)s", value):
                return value
            return recursively_format_str(value=format_str(value))

        return recursively_format_str(raw_value)

    def _stringify_val(
        self,
        raw_value: _TomlValue,
        *,
        option: str,
        section: str,
        section_values: Dict,
        interpolate: bool = True,
        list_prefix: Optional[str] = None,
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
    def sections(self) -> List[str]:
        sections: List[str] = []

        def recurse(mapping: Dict, *, parent_section: Optional[str] = None) -> None:
            for section, section_values in mapping.items():
                if not isinstance(section_values, dict):
                    continue
                # We filter out "DEFAULT" and also check for the special `my_list_option.add` and
                # `my_list_option.remove` syntax.
                if section == "DEFAULT" or "add" in section_values or "remove" in section_values:
                    continue
                section_name = section if not parent_section else f"{parent_section}.{section}"
                if self._section_explicitly_defined(section_values):
                    sections.append(section_name)
                recurse(section_values, parent_section=section_name)

        recurse(self.values)
        return sections

    def has_section(self, section: str) -> bool:
        return self._find_section_values(section) is not None

    def has_option(self, section: str, option: str) -> bool:
        try:
            self.get_value(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return False
        else:
            return True

    def get_value(self, section: str, option: str) -> Optional[str]:
        section_values = self._find_section_values(section)
        if section_values is None:
            raise configparser.NoSectionError(section)
        stringify = partial(
            self._stringify_val,
            option=option,
            section=section,
            section_values=section_values,
        )
        if option not in section_values:
            if option not in self.defaults:
                raise configparser.NoOptionError(option, section)
            return stringify(raw_value=self.defaults[option])
        option_value = section_values[option]
        # Handle the special `my_list_option.add` and `my_list_option.remove` syntax.
        if isinstance(option_value, dict):
            has_add = "add" in option_value
            has_remove = "remove" in option_value
            if not has_add and not has_remove:
                raise configparser.NoOptionError(option, section)
            add_val = stringify(option_value["add"], list_prefix="+") if has_add else None
            remove_val = stringify(option_value["remove"], list_prefix="-") if has_remove else None
            if has_add and has_remove:
                return f"{add_val},{remove_val}"
            if has_add:
                return add_val
            return remove_val
        return stringify(option_value)

    def options(self, section: str) -> List[str]:
        section_values = self._find_section_values(section)
        if section_values is None:
            raise configparser.NoSectionError(section)
        result = [
            option
            for option, option_value in section_values.items()
            if self._is_an_option(option_value)
        ]
        result.extend(
            default_option
            for default_option in self.defaults.keys()
            if default_option not in result
        )
        return result

    @property
    def defaults(self) -> Mapping[str, str]:
        return {
            option: self._stringify_val_without_interpolation(option_val)
            for option, option_val in self.values["DEFAULT"].items()
        }


@dataclass(frozen=True)
class _EmptyConfig(Config):
    """A dummy config with no data at all."""

    def sources(self) -> List[str]:
        return []

    def configs(self) -> List["_SingleFileConfig"]:
        return []

    def sections(self) -> List[str]:
        return []

    def has_section(self, section: str) -> Literal[False]:
        return False

    def has_option(self, section: str, option: str) -> Literal[False]:
        return False

    def get_value(self, section: str, option: str) -> None:
        return None

    def get_source_for_option(self, section: str, option: str) -> None:
        return None

    def __repr__(self) -> str:
        return "EmptyConfig()"


@dataclass(frozen=True, eq=False)
class _SingleFileConfig(Config):
    """Config read from a single file."""

    config_path: str
    content_digest: str
    values: _ConfigValues

    def configs(self) -> List["_SingleFileConfig"]:
        return [self]

    def sources(self) -> List[str]:
        return [self.config_path]

    def sections(self) -> List[str]:
        return self.values.sections

    def has_section(self, section: str) -> bool:
        return self.values.has_section(section)

    def has_option(self, section: str, option: str) -> bool:
        return self.values.has_option(section, option)

    def get_value(self, section: str, option: str) -> Optional[str]:
        return self.values.get_value(section, option)

    def get_source_for_option(self, section: str, option: str) -> Optional[str]:
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
    chained_configs: Tuple[_SingleFileConfig, ...]

    @property
    def _configs(self) -> Tuple[_SingleFileConfig, ...]:
        return self.chained_configs

    def configs(self) -> Tuple[_SingleFileConfig, ...]:
        return self.chained_configs

    def sources(self) -> List[str]:
        # NB: Present the sources in the order we were given them.
        return list(itertools.chain.from_iterable(cfg.sources() for cfg in reversed(self._configs)))

    def sections(self) -> List[str]:
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

    def get_value(self, section: str, option: str) -> Optional[str]:
        for cfg in self._configs:
            try:
                return cfg.get_value(section, option)
            except (configparser.NoSectionError, configparser.NoOptionError):
                pass
        if not self.has_section(section):
            raise configparser.NoSectionError(section)
        raise configparser.NoOptionError(option, section)

    def get_source_for_option(self, section: str, option: str) -> Optional[str]:
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
        "cache.java": {
          "dict_option": {
            "a": 0,
            "b": 0,
          },
        },
      }
    """

    parsed: Mapping[str, Dict[str, Union[int, float, str, bool, List, Dict]]]

    def normalize(self) -> Dict:
        result: Dict = {}
        for section, section_values in self.parsed.items():
            # With TOML, we store dict values as strings to avoid ambiguity between sections/option
            # scopes vs. dict values.
            section_values = {
                option: str(option_value) if isinstance(option_value, dict) else option_value
                for option, option_value in section_values.items()
            }

            def add_section_values(
                section_component: str,
                seen_section_components: List[str],
                remaining_section_components: List[str],
            ) -> None:
                current_scope = result
                for seen in seen_section_components:
                    current_scope = current_scope[seen]
                if not remaining_section_components:
                    current_scope[section_component] = section_values
                    return
                child_section_component = remaining_section_components[0]
                current_scope[section_component] = {child_section_component: {}}
                add_section_values(
                    section_component=child_section_component,
                    seen_section_components=[*seen_section_components, section_component],
                    remaining_section_components=remaining_section_components[1:],
                )

            section_components = section.split(".")
            add_section_values(
                section_component=section_components[0],
                seen_section_components=[],
                remaining_section_components=section_components[1:],
            )

        return result

    def serialize(self) -> str:
        toml_values = self.normalize()
        return toml.dumps(toml_values)
