# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import getpass
import io
import itertools
import os
from abc import ABC
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, ClassVar, List, Optional, Sequence, Tuple

from twitter.common.collections import OrderedSet
from typing_extensions import Literal

from pants.base.build_environment import get_buildroot, get_pants_cachedir, get_pants_configdir
from pants.util.eval import parse_expression


class Config(ABC):
  """Encapsulates ini-style config file loading and access.

  Supports recursive variable substitution using standard python format strings. E.g.,
  %(var_name)s will be replaced with the value of var_name.
  """
  DEFAULT_SECTION: ClassVar[str] = configparser.DEFAULTSECT

  class ConfigError(Exception):
    pass

  class ConfigValidationError(ConfigError):
    pass

  @classmethod
  def load_file_contents(cls, file_contents, seed_values=None):
    """Loads config from the given string payloads.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values.

    :param list[FileContents] file_contents: Load from these FileContents. Later instances take
                                             precedence over earlier ones. If empty, returns an
                                             empty config.
    :param seed_values: A dict with optional override seed values for buildroot, pants_workdir,
                        pants_supportdir and pants_distdir.
    """

    @contextmanager
    def opener(file_content):
      with io.BytesIO(file_content.content) as fh:
        yield fh

    return cls._meta_load(opener, file_contents, seed_values=seed_values)

  @classmethod
  def load(cls, config_paths, seed_values=None) -> "Config":
    """Loads config from the given paths.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values.

    :param list config_paths: Load from these paths. Later instances take precedence over earlier
                              ones. If empty, returns an empty config.
    :param seed_values: A dict with optional override seed values for buildroot, pants_workdir,
                        pants_supportdir and pants_distdir.
    """

    @contextmanager
    def opener(f):
      with open(f, 'rb') as fh:
        yield fh

    return cls._meta_load(opener, config_paths, seed_values=seed_values)

  @classmethod
  def _meta_load(cls, open_ctx, config_items, *, seed_values=None) -> "Config":
    if not config_items:
      return _EmptyConfig()

    single_file_configs = []
    for config_item in config_items:
      parser = cls._create_parser(seed_values=seed_values)
      with open_ctx(config_item) as ini:
        content = ini.read()
        content_digest = sha1(content).hexdigest()
        parser.read_string(content.decode())
      config_path = config_item.path if hasattr(config_item, 'path') else config_item
      single_file_configs.append(_SingleFileConfig(config_path, content_digest, parser))

    return _ChainedConfig(tuple(reversed(single_file_configs)))

  @classmethod
  def _create_parser(cls, *, seed_values=None):
    """Creates a config parser that supports %([key-name])s value substitution.

    A handful of seed values will be set to act as if specified in the loaded config file's DEFAULT
    section, and be available for use in substitutions.  The caller may override some of these
    seed values.

    :param seed_values: A dict with optional override seed values for buildroot, pants_workdir,
                        pants_supportdir and pants_distdir.
    """
    seed_values = seed_values or {}
    buildroot = seed_values.get('buildroot')
    if buildroot is None:
      buildroot = get_buildroot()

    all_seed_values = {
      'buildroot': buildroot,
      'homedir': os.path.expanduser('~'),
      'user': getpass.getuser(),
      'pants_bootstrapdir': get_pants_cachedir(),
      'pants_configdir': get_pants_configdir(),
    }

    def update_dir_from_seed_values(key, default):
      all_seed_values[key] = seed_values.get(key, os.path.join(buildroot, default))

    update_dir_from_seed_values('pants_workdir', '.pants.d')
    update_dir_from_seed_values('pants_supportdir', 'build-support')
    update_dir_from_seed_values('pants_distdir', 'dist')

    return configparser.ConfigParser(all_seed_values)

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

  # Subclasses must implement.
  def configs(self) -> Sequence["Config"]:
    """Returns the underlying single-file configs represented by this object."""
    raise NotImplementedError()

  def sources(self) -> Sequence[str]:
    """Returns the sources of this config as a list of filenames."""
    raise NotImplementedError()

  def sections(self) -> List[str]:
    """Returns the sections in this config (not including DEFAULT)."""
    raise NotImplementedError()

  def has_section(self, section: str) -> bool:
    """Returns whether this config has the section."""
    raise NotImplementedError()

  def has_option(self, section: str, option: str) -> bool:
    """Returns whether this config specified a value the option."""
    raise NotImplementedError()

  def get_value(self, section: str, option: str) -> Optional[str]:
    """Returns the value of the option in this config as a string, or None if no value specified."""
    raise NotImplementedError()

  def get_source_for_option(self, section: str, option: str) -> Optional[str]:
    """Returns the path to the source file the given option was defined in.

    :param section: the scope of the option.
    :param option: the name of the option.
    :returns: the path to the config file, or None if the option was not defined by a config file.
    """
    raise NotImplementedError


@dataclass(frozen=True)
class _EmptyConfig(Config):
  """A dummy config with no data at all."""

  def sources(self) -> List[str]:
    return []

  def configs(self) -> List[Config]:
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


class _SingleFileConfig(Config):
  """Config read from a single file.

  NB: In order to have:
    1. a specialized implementation of __eq__ and __hash__ that avoids comparing file contents
    2. equality ignore the ConfigParser instance
  ...this is not a dataclass.
  """

  def __init__(
    self, configpath: str, content_digest: str, configparser: configparser.ConfigParser,
  ) -> None:
    super().__init__()
    self.configpath = configpath
    self.content_digest = content_digest
    self.configparser = configparser

  def configs(self) -> List[Config]:
    return [self]

  def sources(self) -> List[str]:
    return [self.configpath]

  def sections(self) -> List[str]:
    return self.configparser.sections()

  def has_section(self, section: str) -> bool:
    return self.configparser.has_section(section)

  def has_option(self, section: str, option: str) -> bool:
    return self.configparser.has_option(section, option)

  def get_value(self, section: str, option: str) -> Optional[str]:
    return self.configparser.get(section, option)

  def get_source_for_option(self, section: str, option: str) -> Optional[str]:
    if self.has_option(section, option):
      return self.sources()[0]
    return None

  def __eq__(self, other: Any) -> bool:
    if not isinstance(other, _SingleFileConfig):
      return NotImplemented
    return self.configpath == other.configpath and self.content_digest == other.content_digest

  def __hash__(self) -> int:
    return hash(self.content_digest)


@dataclass(frozen=True)
class _ChainedConfig(Config):
  """Config read from multiple sources.

  :param chained_configs: A tuple of Config instances to chain. Later instances take precedence
                          over earlier ones.
  """
  chained_configs: Tuple[Config, ...]

  @property
  def _configs(self) -> Tuple[Config, ...]:
    return self.chained_configs

  def configs(self) -> Tuple[Config, ...]:
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
