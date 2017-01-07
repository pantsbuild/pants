# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple
from difflib import SequenceMatcher

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.jvm_compile.class_not_found_error_patterns import \
  CLASS_NOT_FOUND_ERROR_PATTERNS


def normalize_classname(classname):
  """
  Ensure the dot separated class name.
  """
  return classname.replace('$', '.').replace('/', '.')


class ClassNotFoundError(namedtuple('CompileError', ['source', 'lineno', 'classname'])):
  """Compilation error specifically about class not found."""
  pass


class CompileErrorExtractor(object):
  """
  Extract `ClassNotFoundError`s from pants compile log.
  """

  def __init__(self, error_patterns=CLASS_NOT_FOUND_ERROR_PATTERNS):
    self._error_patterns = error_patterns

  def extract(self, compile_output):
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
        classname = normalize_classname(classname)
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

    return errors


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


class MissingDependencyFinder(object):
  """
  Try to find missing dependencies from target's transitive dependencies.
  """

  def __init__(self, dep_analyzer):
    self.dep_analyzer = dep_analyzer
    self.compile_error_extractor = CompileErrorExtractor()

  def find(self, compile_failure_log, target):
    not_found_classes = [err.classname for err in
                         self.compile_error_extractor.extract(compile_failure_log)]
    return self.select_target_candidates_for_class(not_found_classes, target)

  def select_target_candidates_for_class(self, classnames, target):
    """Select top candidate for a given classname.

    When multiple candidates are available, sometimes common in 3rdparty dependencies,
    they are ranked according to their similiarities with the classname because the way
    3rdparty targets are conventionally named.
    """
    candiates = {}
    for classname in classnames:
      if classname not in candiates:
        candidates_for_class = [tgt.address.spec for tgt in
                                self.dep_analyzer.targets_for_class(target, classname)]
        if candidates_for_class:
          candidates_for_class = StringSimilarityRanker(classname).sort(candidates_for_class)
          candiates[classname] = OrderedSet(candidates_for_class)
        else:
          candiates[classname] = set()
    return candiates
