# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.exceptions import TaskError
from pants.base.revision import Revision
from pants.java.distribution.distribution import DistributionLocator
from pants.option.custom_types import dict_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property


logger = logging.getLogger(__name__)


class JvmPlatform(Subsystem):
  """Used to keep track of repo compile settings."""

  # NB(gmalmquist): These assume a java version number N can be specified as either 'N' or '1.N'
  # (eg, '7' is equivalent to '1.7'). New versions should only be added to this list
  # if they follow this convention. If this convention is ever not followed for future
  # java releases, they can simply be omitted from this list and they will be parsed
  # strictly (eg, if Java 10 != 1.10, simply leave it out).
  SUPPORTED_CONVERSION_VERSIONS = (6, 7, 8,)

  class IllegalDefaultPlatform(TaskError):
    """The --default-platform option was set, but isn't defined in --platforms."""

  class UndefinedJvmPlatform(TaskError):
    """Platform isn't defined."""

    def __init__(self, target, platform_name, platforms_by_name):
      scope_name = JvmPlatform.options_scope
      messages = ['Undefined jvm platform "{}" (referenced by {}).'
                    .format(platform_name, target.address.spec if target else 'unknown target')]
      if not platforms_by_name:
        messages.append('In fact, no platforms are defined under {0}. These should typically be'
                        ' specified in [{0}] in pants.ini.'.format(scope_name))
      else:
        messages.append('Perhaps you meant one of:{}'.format(
          ''.join('\n  {}'.format(name) for name in sorted(platforms_by_name.keys()))
        ))
        messages.append('\nThese are typically defined under [{}] in pants.ini.'
                        .format(scope_name))
      super(JvmPlatform.UndefinedJvmPlatform, self).__init__(' '.join(messages))

  options_scope = 'jvm-platform'

  # Mapping to keep version numbering consistent for ease of comparison.
  @classmethod
  def register_options(cls, register):
    super(JvmPlatform, cls).register_options(register)
    register('--platforms', advanced=True, type=dict_option, default={}, fingerprint=True,
             help='Compile settings that can be referred to by name in jvm_targets.')
    register('--default-platform', advanced=True, type=str, default=None, fingerprint=True,
             help='Name of the default platform to use if none are specified.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(JvmPlatform, cls).subsystem_dependencies() + (DistributionLocator,)

  def _parse_platform(self, name, platform):
    return JvmPlatformSettings(platform.get('source', platform.get('target')),
                               platform.get('target', platform.get('source')),
                               platform.get('args', ()),
                               name=name)

  @memoized_property
  def platforms_by_name(self):
    platforms = self.get_options().platforms or {}
    return {name: self._parse_platform(name, platform) for name, platform in platforms.items()}

  @property
  def _fallback_platform(self):
    logger.warn('No default jvm platform is defined.')
    source_level = JvmPlatform.parse_java_version(DistributionLocator.cached().version)
    target_level = source_level
    platform_name = '(DistributionLocator.cached().version {})'.format(source_level)
    return JvmPlatformSettings(source_level, target_level, [], name=platform_name)

  @memoized_property
  def default_platform(self):
    name = self.get_options().default_platform
    if not name:
      return self._fallback_platform
    platforms_by_name = self.platforms_by_name
    if name not in platforms_by_name:
      raise self.IllegalDefaultPlatform(
          "The default platform was set to '{0}', but no platform by that name has been "
          "defined. Typically, this should be defined under [{1}] in pants.ini."
          .format(name, self.options_scope)
      )
    return JvmPlatformSettings(*platforms_by_name[name], name=name, by_default=True)

  @memoized_method
  def get_platform_by_name(self, name, for_target=None):
    """Finds the platform with the given name.

    If the name is empty or None, returns the default platform.
    If not platform with the given name is defined, raises an error.
    :param str name: name of the platform.
    :param JvmTarget for_target: optionally specified target we're looking up the platform for.
      Only used in error message generation.
    :return: The jvm platform object.
    :rtype: JvmPlatformSettings
    """
    if not name:
      return self.default_platform
    if name not in self.platforms_by_name:
      raise self.UndefinedJvmPlatform(for_target, name, self.platforms_by_name)
    return self.platforms_by_name[name]

  def get_platform_for_target(self, target):
    """Find the platform associated with this target.

    :param JvmTarget target: target to query.
    :return: The jvm platform object.
    :rtype: JvmPlatformSettings
    """
    if not target.payload.platform and target.is_synthetic:
      derived_from = target.derived_from
      platform = derived_from and getattr(derived_from, 'platform', None)
      if platform:
        return platform
    return self.get_platform_by_name(target.payload.platform, target)

  @classmethod
  def parse_java_version(cls, version):
    """Parses the java version (given a string or Revision object).

    Handles java version-isms, converting things like '7' -> '1.7' appropriately.

    Truncates input versions down to just the major and minor numbers (eg, 1.6), ignoring extra
    versioning information after the second number.

    :param version: the input version, given as a string or Revision object.
    :return: the parsed and cleaned version, suitable as a javac -source or -target argument.
    :rtype: Revision
    """
    conversion = {str(i): '1.{}'.format(i) for i in cls.SUPPORTED_CONVERSION_VERSIONS}
    if str(version) in conversion:
      return Revision.lenient(conversion[str(version)])

    if not hasattr(version, 'components'):
      version = Revision.lenient(version)
    if len(version.components) <= 2:
      return version
    return Revision(*version.components[:2])


class JvmPlatformSettings(object):
  """Simple information holder to keep track of common arguments to java compilers."""

  class IllegalSourceTargetCombination(TaskError):
    """Illegal pair of -source and -target flags to compile java."""

  def __init__(self, source_level, target_level, args, name=None, by_default=False):
    """
    :param source_level: Revision object or string for the java source level.
    :param target_level: Revision object or string for the java target level.
    :param list args: Additional arguments to pass to the java compiler.
    :param str name: name to identify this platform.
    :param by_default: True if this value was inferred by omission of a specific platform setting.
    """
    self.source_level = JvmPlatform.parse_java_version(source_level)
    self.target_level = JvmPlatform.parse_java_version(target_level)
    self.args = tuple(args or ())
    self.name = name
    self._by_default = by_default
    self._validate_source_target()

  def _validate_source_target(self):
    if self.source_level > self.target_level:
      if self.by_default:
        name = "{} (by default)".format(self.name)
      else:
        name = self.name
      raise self.IllegalSourceTargetCombination(
        'Platform {platform} has java source level {source_level} but target level {target_level}.'
        .format(platform=name,
                source_level=self.source_level,
                target_level=self.target_level)
      )

  @property
  def by_default(self):
    return self._by_default

  def __iter__(self):
    yield self.source_level
    yield self.target_level
    yield self.args

  def __eq__(self, other):
    return tuple(self) == tuple(other)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(tuple(self))

  def __cmp__(self, other):
    return cmp(tuple(self), tuple(other))

  def __str__(self):
    return 'source={source},target={target},args=({args})'.format(
      source=self.source_level,
      target=self.target_level,
      args=' '.join(self.args)
    )
