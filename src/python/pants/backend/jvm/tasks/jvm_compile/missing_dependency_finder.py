# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from collections import namedtuple
from difflib import SequenceMatcher

from colors import strip_color
from twitter.common.collections import OrderedSet


def normalize_classname(classname):
  """
  Ensure the dot separated class name (zinc reported class not found may use '/' separator)
  """
  return classname.replace('/', '.')


class ClassNotFoundError(namedtuple('CompileError', ['source', 'lineno', 'classname'])):
  """Represents class not found compile errors."""
  pass


class CompileErrorExtractor(object):
  """
  Extract `ClassNotFoundError`s from pants compile log.
  """

  def __init__(self, error_patterns):
    self._error_patterns = [re.compile(p) for p in error_patterns]

  def extract(self, compile_output):
    def safe_get_named_group(match, name):
      try:
        return match.group(name)
      except IndexError:
        return None

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
    compile_output = strip_color(compile_output)
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

  def __init__(self, dep_analyzer, error_extractor):
    self.dep_analyzer = dep_analyzer
    self.compile_error_extractor = error_extractor

  def find(self, compile_failure_log, target):
    """Find missing deps on a best-effort basis from target's transitive dependencies.

    Returns (class2deps, no_dep_found) tuple. `class2deps` contains classname
    to deps that contain the class mapping. `no_dep_found` are the classnames that are
    unable to find the deps.
    """
    not_found_classnames = [err.classname for err in
                            self.compile_error_extractor.extract(compile_failure_log)]
    return self._select_target_candidates_for_class(not_found_classnames, target)

  def _select_target_candidates_for_class(self, classnames, target):
    """Select a target that contains the given classname.

    When multiple candidates are available, not uncommon in 3rdparty dependencies,
    they are ranked according to their string similiarities with the classname because
    the way 3rdparty targets are conventionally named often shares similar naming
    structure.
    """
    class2deps, no_dep_found = {}, set()
    for classname in classnames:
      if classname not in class2deps:
        candidates_for_class = []
        for tgt in self.dep_analyzer.targets_for_class(target, classname):
          if tgt.is_synthetic and tgt.derived_from:
            tgt = tgt.derived_from
          candidates_for_class.append(tgt.address.spec)
        if candidates_for_class:
          candidates_for_class = StringSimilarityRanker(classname).sort(candidates_for_class)
          class2deps[classname] = OrderedSet(candidates_for_class)
        else:
          no_dep_found.add(classname)
    return class2deps, no_dep_found
