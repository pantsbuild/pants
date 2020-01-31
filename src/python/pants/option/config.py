# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import getpass
import io
import itertools
import os
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple, Union, cast

from twitter.common.collections import OrderedSet
from typing_extensions import Literal

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.option.ranked_value import Value
from pants.util.eval import parse_expression


# A dict with optional override seed values for buildroot, pants_workdir, pants_supportdir and
# pants_distdir.
SeedValues = Dict[str, Value]


class Config(ABC):
  """Encapsulates config file loading and access, including encapsulation of support for
  multiple config files.

  Supports variable substitution using old-style Python format strings. E.g.,
  %(var_name)s will be replaced with the value of var_name.
  """
  DEFAULT_SECTION: ClassVar[str] = configparser.DEFAULTSECT

  class ConfigError(Exception):
    pass

  class ConfigValidationError(ConfigError):
    pass

  @classmethod
  def load_file_contents(
    cls, file_contents, *, seed_values: Optional[SeedValues] = None,
  ) -> Union["_EmptyConfig", "_ChainedConfig"]:
    """Loads config from the given string payloads, with later payloads taking precedence over
    earlier ones.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values."""

    @contextmanager
    def opener(file_content):
      with io.BytesIO(file_content.content) as fh:
        yield fh

    return cls._meta_load(opener, file_contents, seed_values=seed_values)

  @classmethod
  def load(
    cls, config_paths: List[str], *, seed_values: Optional[SeedValues] = None,
  ) -> Union["_EmptyConfig", "_ChainedConfig"]:
    """Loads config from the given paths, with later paths taking precedence over earlier ones.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values."""

    @contextmanager
    def opener(f):
      with open(f, 'rb') as fh:
        yield fh

    return cls._meta_load(opener, config_paths, seed_values=seed_values)

  @classmethod
  def _meta_load(
    cls, open_ctx, config_items: Sequence, *, seed_values: Optional[SeedValues] = None,
  ) -> Union["_EmptyConfig", "_ChainedConfig"]:
    if not config_items:
      return _EmptyConfig()

    single_file_configs = []
    for config_item in config_items:
      config_path = config_item.path if hasattr(config_item, "path") else config_item
      with open_ctx(config_item) as config_file:
        content = config_file.read()
      content_digest = sha1(content).hexdigest()
      normalized_seed_values = cls._determine_seed_values(seed_values=seed_values)

      ini_parser = configparser.ConfigParser(defaults=normalized_seed_values)
      ini_parser.read_string(content.decode())
      single_file_configs.append(
        _SingleFileConfig(
          config_path=config_path, content_digest=content_digest, values=_IniValues(ini_parser),
        ),
      )
    return _ChainedConfig(tuple(reversed(single_file_configs)))

  @staticmethod
  def _determine_seed_values(*, seed_values: Optional[SeedValues] = None) -> Dict[str, str]:
    """We pre-populate several default values to allow %([key-name])s interpolation.

    This sets up those defaults and checks if the user overrided any of the values."""
    safe_seed_values = seed_values or {}
    buildroot = cast(str, safe_seed_values.get('buildroot', get_buildroot()))

    all_seed_values: Dict[str, str] = {
      'buildroot': buildroot,
      'homedir': os.path.expanduser('~'),
      'user': getpass.getuser(),
      'pants_bootstrapdir': get_pants_cachedir(),
      'pants_configdir': get_pants_configdir(),
    }

    def update_seed_values(key: str, *, default_dir: str) -> None:
      all_seed_values[key] = cast(str, safe_seed_values.get(key, os.path.join(buildroot, default_dir)))

    update_seed_values('pants_workdir', default_dir='.pants.d')
    update_seed_values('pants_supportdir', default_dir='build-support')
    update_seed_values('pants_distdir', default_dir='dist')

    return all_seed_values

  def get(self, section, option, type_=str, default=None):
    """Retrieves option from the specified section (or 'DEFAULT') and attempts to parse it as type.

    If the specified section does not exist or is missing a definition for the option, the value is
    looked up in the DEFAULT section.  If there is still no definition found, the default value
    supplied is returned.
    """
    return self._getinstance(section, option, type_, default)

  def _getinstance(self, section, option, type_, default=None):
    if not self.has_option(section, option):
      return default

    raw_value = self.get_value(section, option)
    if type_ == str or issubclass(type_, str):
      return raw_value

    key = f'{section}.{option}'
    return parse_expression(name=key, val=raw_value, acceptable_types=type_,
                            raise_type=self.ConfigError)

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
    """Returns the value of the option in this config as a string, or None if no value specified."""

  @abstractmethod
  def get_source_for_option(self, section: str, option: str) -> Optional[str]:
    """Returns the path to the source file the given option was defined in.

    :param section: the scope of the option.
    :param option: the name of the option.
    :returns: the path to the config file, or None if the option was not defined by a config file.
    """


class _ConfigValues(ABC):
  """Encapsulates resolving the actual config values specified by the user's config file.

  Beyond providing better encapsulation, this allows us to support alternative config file formats
  in the future if we ever decide to support formats other than INI.
  """

  @abstractmethod
  def sections(self) -> List[str]:
    """Returns the sections in this config (not including DEFAULT)."""

  @abstractmethod
  def has_section(self, section: str) -> bool:
    pass

  @abstractmethod
  def has_option(self, section: str, option: str) -> bool:
    pass

  @abstractmethod
  def get_value(self, section: str, option: str) -> Optional[str]:
    pass

  @abstractmethod
  def options(self, section: str) -> List[str]:
    """All options defined for the section."""

  @abstractmethod
  def defaults(self) -> Mapping[str, Any]:
    """All the DEFAULT values (not interpolated)."""


@dataclass(frozen=True)
class _IniValues(_ConfigValues):
  parser: configparser.ConfigParser

  def sections(self) -> List[str]:
    return self.parser.sections()

  def has_section(self, section: str) -> bool:
    return self.parser.has_section(section)

  def has_option(self, section: str, option: str) -> bool:
    return self.parser.has_option(section, option)

  def get_value(self, section: str, option: str) -> Optional[str]:
    return self.parser.get(section, option)

  def options(self, section: str) -> List[str]:
    return self.parser.options(section)

  def defaults(self) -> Mapping[str, str]:
    return self.parser.defaults()


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
    return self.values.sections()

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

  def __eq__(self, other: Any) -> bool:
    if not isinstance(other, _SingleFileConfig):
      return NotImplemented
    return self.config_path == other.config_path and self.content_digest == other.content_digest

  def __hash__(self) -> int:
    return hash(self.content_digest)


@dataclass(frozen=True)
class _ChainedConfig(Config):
  """Config read from multiple sources.

  :param chained_configs: A tuple of Config instances to chain. Later instances take precedence
                          over earlier ones.
  """
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
    ret = OrderedSet()
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
