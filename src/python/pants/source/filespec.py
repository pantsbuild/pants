# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re


def glob_to_regex(pattern):
  """Given a glob pattern, return an equivalent regex expression.
  :param string glob: The glob pattern. "**" matches 0 or more dirs recursively.
                      "*" only matches patterns in a single dir.
  :returns: A regex string that matches same paths as the input glob does.
  """
  out = ['^']
  components = pattern.strip('/').replace('.', '[.]').replace('$','[$]').split('/')
  doublestar = False
  for component in components:
    if len(out) == 1:
      if pattern.startswith('/'):
        out.append('/')
    else:
      if not doublestar:
        out.append('/')

    if '**' in component:
      if component != '**':
        raise ValueError('Invalid usage of "**", use "*" instead.')

      if not doublestar:
        out.append('(([^/]+/)*)')
        doublestar = True
    else:
      out.append(component.replace('*', '[^/]*'))
      doublestar = False

  if doublestar:
    out.append('[^/]*')

  out.append('$')

  return ''.join(out)


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
