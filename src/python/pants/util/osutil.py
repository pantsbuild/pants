# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.util.memo import memoized_method
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


_ID_BY_OS = {
  'linux': lambda release, machine: ('linux', machine),
  'darwin': lambda release, machine: ('darwin', release.split('.')[0]),
}


OS_ALIASES = {
  'darwin': {'macos', 'darwin', 'macosx', 'mac os x', 'mac'},
  'linux': {'linux', 'linux2'},
}


SUPPORTED_PLATFORM_NORMALIZED_NAMES = {
  ('linux', 'x86_64'): ('linux', 'x86_64'),
  ('linux', 'amd64'): ('linux', 'x86_64'),
  ('linux', 'i386'): ('linux', 'i386'),
  ('linux', 'i686'): ('linux', 'i386'),
  ('darwin', '9'): ('mac', '10.5'),
  ('darwin', '10'): ('mac', '10.6'),
  ('darwin', '11'): ('mac', '10.7'),
  ('darwin', '12'): ('mac', '10.8'),
  ('darwin', '13'): ('mac', '10.9'),
  ('darwin', '14'): ('mac', '10.10'),
  ('darwin', '15'): ('mac', '10.11'),
  ('darwin', '16'): ('mac', '10.12'),
  ('darwin', '17'): ('mac', '10.13'),
}


# TODO: make a SingletonRule for this somewhere?
class OsId(datatype(['name', 'arch'])):

  class MissingMachineInfo(Exception):
    """???/change the name to be different than in BinaryUtil or HostPlatform"""

  # TODO(cosmicexplorer): Would this benefit from @memoized_method?
  @classmethod
  def from_uname(cls, uname_result):
    sysname, _, release, _, machine = uname_result
    os_id = _ID_BY_OS.get(sysname.lower())

    if os_id:
      return cls(*os_id(release, machine))

    raise cls.MissingMachineInfo(
      "Pants could not recognize this platform: {}".format(uname_result))

  @classmethod
  @memoized_method
  def for_current_platform(cls):
    return cls.from_uname(os.uname())


def get_os_name():
  """
  :API: public
  """
  return os.uname()[0].lower()


def get_os_id(uname_func=None):
  """Return an OS identifier sensitive only to its major version.

  :param uname_func: An `os.uname` compliant callable; intended for tests.
  :returns: a tuple of (OS name, sub identifier) or `None` if the OS is not supported.
  :rtype: tuple of string, string
  """
  uname_func = uname_func or os.uname
  try:
    os_id_obj = OsId.from_uname(uname_func())
    return (os_id_obj.name, os_id_obj.arch)
  except OsId.MissingMachineInfo:
    return None


def normalize_os_name(os_name):
  """
  :API: public
  """
  if os_name not in OS_ALIASES:
    for proper_name, aliases in OS_ALIASES.items():
      if os_name in aliases:
        return proper_name
    logger.warning('Unknown operating system name: {bad}, known names are: {known}'
                   .format(bad=os_name, known=', '.join(sorted(known_os_names()))))
  return os_name


def get_normalized_os_name():
  return normalize_os_name(get_os_name())


def all_normalized_os_names():
  return OS_ALIASES.keys()


def known_os_names():
  return reduce(set.union, OS_ALIASES.values())
