# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.util.fileutil import glob_to_regex


def globs_matches(path, patterns):
  return any(re.match(glob_to_regex(pattern), path) for pattern in patterns)


def matches_filespec(path, spec):
  if spec is None:
    return False
  if not globs_matches(path, spec.get('globs', [])):
    return False
  for spec in spec.get('exclude', []):
    if matches_filespec(path, spec):
      return False
  return True
