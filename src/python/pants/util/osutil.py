# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from functools import reduce


logger = logging.getLogger(__name__)


OS_ALIASES = {
  'darwin': {'macos', 'darwin', 'macosx', 'mac os x', 'mac'},
  'linux': {'linux', 'linux2'},
}


def get_os_name(uname_result=None):
  """
  :API: public
  """
  if uname_result is None:
    uname_result = os.uname()
  return uname_result[0].lower()


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
  return list(OS_ALIASES.keys())


def known_os_names():
  return reduce(set.union, OS_ALIASES.values())


# TODO(cosmicexplorer): use this as the default value for the global --binaries-path-by-id option!
# panstd testing fails saying no run trackers were created when I tried to do this.
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
