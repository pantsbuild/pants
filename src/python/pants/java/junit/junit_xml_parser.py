# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import fnmatch
import os
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.util.dirutil import safe_walk
from pants.util.objects import datatype
from pants.util.xml_parser import XmlParser


class Test(datatype('Test', ['classname', 'methodname'])):
  """Describes a junit-style test or collection of tests."""

  def __new__(cls, classname, methodname=None):
    # We deliberately normalize an empty methodname ('') to None.
    return super(Test, cls).__new__(cls, classname, methodname or None)

  def enclosing(self):
    """Return a test representing all the tests in this test's enclosing class.

    :returns: A test representing this test's enclosing test class if this test represents a test
              method or else just this test if it specifies no method.
    :rtype: :class:`Test`
    """
    return self if self.methodname is None else Test(classname=self.classname)

  def render_test_spec(self):
    """Renders this test in `[classname]#[methodname]` test specification format.

    :returns: A rendering of this test in the semi-standard test specification format.
    :rtype: string
    """
    if self.methodname is None:
      return self.classname
    else:
      return '{}#{}'.format(self.classname, self.methodname)


class RegistryOfTests(object):
  """A registry of tests and the targets that own them."""

  def __init__(self, mapping_or_seq):
    """Creates a test registry mapping tests to their owning targets.

    :param mapping_or_seq: A dictionary from tests to the targets that own them or else a sequence
                           of 2-tuples containing a test in the 1st slot and its owning target in
                           the second.
    :type mapping_or_seq: A :class:`collections.Mapping` from :class:`Test` to
                          :class:`pants.build_graph.target.Target` or else a sequence of
                          (:class:`Test`, :class:`pants.build_graph.target.Target`) tuples.
    """
    self._test_to_target = dict(mapping_or_seq)

  @property
  def empty(self):
    """Return true if there are no registered tests.

    :returns: `True` if this registry is empty.
    :rtype: bool
    """
    return len(self._test_to_target) == 0

  def get_owning_target(self, test):
    """Return the target that owns the given test.

    :param test: The test to find an owning target for.
    :type test: :class:`Test`
    :returns: The target that owns the given `test` or else `None` if the owning target is unknown.
    :rtype: :class:`pants.build_graph.target.Target`
    """
    target = self._test_to_target.get(test)
    if target is None:
      target = self._test_to_target.get(test.enclosing())
    return target

  def index(self, *indexers):
    """Indexes the tests in this registry by sets of common properties their owning targets share.

    :param indexers: Functions that index a target, producing a hashable key for a given property.
    :return: An index of tests by shared properties.
    :rtype: dict from tuple of properties to a tuple of :class:`Test`.
    """
    def combined_indexer(tgt):
      return tuple(indexer(tgt) for indexer in indexers)

    properties = defaultdict(OrderedSet)
    for test, target in self._test_to_target.items():
      properties[combined_indexer(target)].add(test)
    return {prop: tuple(tests) for prop, tests in properties.items()}


class ParseError(Exception):
  """Indicates an error parsing a junit xml report file."""

  def __init__(self, junit_xml_path, cause):
    super(ParseError, self).__init__('Error parsing test result file {}: {}'
                                     .format(junit_xml_path, cause))
    self._junit_xml_path = junit_xml_path
    self._cause = cause

  @property
  def junit_xml_path(self):
    """Return the path of the file the parse error was encountered in.

    :return: The path of the file the parse error was encountered in.
    :rtype: string
    """
    return self._junit_xml_path

  @property
  def cause(self):
    """Return the cause of the parse error.

    :return: The cause of the parse error.
    :rtype: :class:`BaseException`
    """
    return self._cause


def parse_failed_targets(test_registry, junit_xml_path, error_handler):
  """Parses junit xml reports and maps targets to the set of individual tests that failed.

  Targets with no failed tests are omitted from the returned mapping and failed tests with no
  identifiable owning target are keyed under `None`.

  :param test_registry: A registry of tests that were run.
  :type test_registry: :class:`RegistryOfTests`
  :param string junit_xml_path: A path to a file or directory containing test junit xml reports
                                to analyze.
  :param error_handler: An error handler that will be called with any junit xml parsing errors.
  :type error_handler: callable that accepts a single :class:`ParseError` argument.
  :returns: A mapping from targets to the set of individual tests that failed. Any failed tests
            that belong to no identifiable target will be mapped to `None`.
  :rtype: dict from :class:`pants.build_graph.target.Target` to a set of :class:`Test`
  """
  failed_targets = defaultdict(set)

  def parse_junit_xml_file(path):
    try:
      xml = XmlParser.from_file(path)
      failures = int(xml.get_attribute('testsuite', 'failures'))
      errors = int(xml.get_attribute('testsuite', 'errors'))
      if failures or errors:
        for testcase in xml.parsed.getElementsByTagName('testcase'):
          test_failed = testcase.getElementsByTagName('failure')
          test_errored = testcase.getElementsByTagName('error')
          if test_failed or test_errored:
            test = Test(classname=testcase.getAttribute('classname'),
                        methodname=testcase.getAttribute('name'))
            target = test_registry.get_owning_target(test)
            failed_targets[target].add(test)
    except (XmlParser.XmlError, ValueError) as e:
      error_handler(ParseError(path, e))

  if os.path.isdir(junit_xml_path):
    for root, _, files in safe_walk(junit_xml_path):
      for junit_xml_file in fnmatch.filter(files, 'TEST-*.xml'):
        parse_junit_xml_file(os.path.join(root, junit_xml_file))
  else:
    parse_junit_xml_file(junit_xml_path)

  return dict(failed_targets)
