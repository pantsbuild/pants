# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple
from difflib import SequenceMatcher

from pants.backend.jvm.tasks.jvm_compile.class_not_found_error_patterns import \
  CLASS_NOT_FOUND_ERROR_PATTERNS


class ClassNotFoundError(namedtuple('CompileError', ['source', 'lineno', 'classname'])):
  """Compilation error specifically about class not found."""
  pass


class CompileErrorExtractor(object):
  """
  Extract `ClassNotFoundError`s from pants compile log.
  """

  def __init__(self, error_patterns=CLASS_NOT_FOUND_ERROR_PATTERNS):
    self._error_patterns = error_patterns

  def extract(self, compile_output, first_only=True):
    def safe_get_named_group(match, name, default=None):
      try:
        return match.group(name)
      except IndexError:
        return default

    def get_matched_error(match):
      source = safe_get_named_group(match, 'filename')
      lineno = safe_get_named_group(match, 'lineno')
      classname = safe_get_named_group(match, 'classname')
      if not classname:
        classnameonly = safe_get_named_group(match, 'classnameonly')
        packagename = safe_get_named_group(match, 'packagename')
        if classnameonly and packagename:
          classname = '.'.join([packagename, classnameonly])
      if classname:
        classname = self._normalize_classname(classname)
      return ClassNotFoundError(source, lineno, classname)

    errors = []
    start = 0
    while start < len(compile_output):
      first_match = None
      for p in self._error_patterns:
        m = p.search(compile_output, start)
        if m:
          if not first_match or m.start() < first_match.start():
            first_match = m

      if not first_match:
        break

      errors.append(get_matched_error(first_match))
      start = first_match.end() + 1

      if first_only:
        break

    return errors

  def _normalize_classname(self, classname):
    """
    Ensure the dot separated class name.
    """
    return classname.replace('$', '.').replace('/', '.')


class StringSimilarityRanker(object):
  """
  Sort strings according to their similarities to a given string.
  """

  def __init__(self, base_str):
    """
    :param base_str: the given string to compute similarity against.
    """
    self._base_str = base_str

  def sort(self, strings):
    return sorted(strings, key=lambda str: SequenceMatcher(a=self._base_str, b=str).ratio(),
      reverse=True)
