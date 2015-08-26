# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os


logger = logging.getLogger(__name__)


_ID_BY_OS = {
  'linux': lambda release, machine: ('linux', machine),
  'darwin': lambda release, machine: ('darwin', release.split('.')[0]),
}


OS_ALIASES = {
  'darwin': {'macos', 'darwin', 'macosx', 'mac os x', 'mac'},
  'linux': {'linux', 'linux2'},
}


def get_os_name():
  return os.uname()[0].lower()


def get_os_id(uname_func=None):
  uname_func = uname_func or os.uname
  sysname, _, release, _, machine = uname_func()
  os_id = _ID_BY_OS[sysname.lower()]
  if os_id:
    return os_id(release, machine)
  return None


def normalize_os_name(os_name):
  if os_name not in OS_ALIASES:
    for proper_name, aliases in OS_ALIASES.items():
      if os_name in aliases:
        return proper_name
    logger.warning('Unknown operating system name: {bad}, known names are: {known}'
                   .format(bad=os_name, known=', '.join(sorted(known_os_names()))))
  return os_name


def known_os_names():
  return reduce(set.union, OS_ALIASES.values())
