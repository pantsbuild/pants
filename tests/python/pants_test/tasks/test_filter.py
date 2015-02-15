# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.doc import Page
from pants.backend.core.tasks.filter import Filter
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.tasks.test_base import ConsoleTaskTest


class BaseFilterTest(ConsoleTaskTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'target': Dependencies,
        'java_library': JavaLibrary,
        'page': Page,
        'python_library': PythonLibrary,
        'python_requirement_library': PythonRequirementLibrary,
      }
    )

  @classmethod
  def task_type(cls):
    return Filter


class FilterEmptyTargetsTest(BaseFilterTest):
  def test_no_filters(self):
    self.assert_console_output()

  def test_type(self):
    self.assert_console_output(args=['--test-type=page'])
    self.assert_console_output(args=['--test-type=-java_library'])

  def test_regex(self):
    self.assert_console_output(args=['--test-regex=^common'])
    self.assert_console_output(args=['--test-regex=-^common'])


class FilterTest(BaseFilterTest):
  def setUp(self):
    super(FilterTest, self).setUp()

    requirement_injected = set()

    def add_to_build_file(path, name, *deps):
      if path not in requirement_injected:
        self.add_to_build_file(path, "python_requirement_library(name='foo')")
        requirement_injected.add(path)
      all_deps = ["'%s'" % dep for dep in deps] + ["':foo'"]
      self.add_to_build_file(path, dedent('''
          python_library(name='%s',
            dependencies=[%s]
          )
          ''' % (name, ','.join(all_deps))))

    add_to_build_file('common/a', 'a')
    add_to_build_file('common/b', 'b')
    add_to_build_file('common/c', 'c')
    add_to_build_file('overlaps', 'one', 'common/a', 'common/b')
    add_to_build_file('overlaps', 'two', 'common/a', 'common/c')
    add_to_build_file('overlaps', 'three', 'common/a', 'overlaps:one')

  def test_roots(self):
    self.assert_console_output(
      'common/a:a',
      'common/a:foo',
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      targets=self.targets('common/::'),
      extra_targets=self.targets('overlaps/::')
    )

  def test_nodups(self):
    targets = [self.target('common/b')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'common/b:b',
      targets=targets
    )

  def test_no_filters(self):
    self.assert_console_output(
      'common/a:a',
      'common/a:foo',
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      'overlaps:one',
      'overlaps:two',
      'overlaps:three',
      'overlaps:foo',
      targets=self.targets('::')
    )

  def test_filter_type(self):
    self.assert_console_output(
      'common/a:a',
      'common/b:b',
      'common/c:c',
      'overlaps:one',
      'overlaps:two',
      'overlaps:three',
      args=['--test-type=python_library'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a:foo',
      'common/b:foo',
      'common/c:foo',
      'overlaps:foo',
      args=['--test-type=-python_library'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a:a',
      'common/a:foo',
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      'overlaps:one',
      'overlaps:two',
      'overlaps:three',
      'overlaps:foo',
      args=['--test-type=python_requirement_library,'
            'pants.backend.python.targets.python_library.PythonLibrary'],
      targets=self.targets('::')
    )

  def test_filter_target(self):
    self.assert_console_output(
      'common/a:a',
      'overlaps:foo',
      args=['--test-target=common/a,overlaps/:foo'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a:foo',
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      'overlaps:two',
      'overlaps:three',
      args=['--test-target=-common/a:a,overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

  def test_filter_ancestor(self):
    self.assert_console_output(
      'common/a:a',
      'common/a:foo',
      'common/b:b',
      'common/b:foo',
      'overlaps:one',
      'overlaps:foo',
      args=['--test-ancestor=overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/c:c',
      'common/c:foo',
      'overlaps:two',
      'overlaps:three',
      args=['--test-ancestor=-overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

  def test_filter_ancestor_out_of_context(self):
    """Tests that targets outside of the context used as filters are parsed before use"""

    # add an additional un-injected target, and then use it as a filter
    self.add_to_build_file("blacklist", "target(name='blacklist', dependencies=['common/a'])")

    self.assert_console_output(
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      'overlaps:one',
      'overlaps:two',
      'overlaps:three',
      'overlaps:foo',
      args=['--test-ancestor=-blacklist'],
      targets=self.targets('::')
    )

  def test_filter_ancestor_not_passed_targets(self):
    """Tests filtering targets based on an ancestor not in that list of targets"""

    # add an additional un-injected target, and then use it as a filter
    self.add_to_build_file("blacklist", "target(name='blacklist', dependencies=['common/a'])")

    self.assert_console_output(
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      args=['--test-ancestor=-blacklist'],
      targets=self.targets('common/::') # blacklist is not in the list of targets
    )

    self.assert_console_output(
      'common/a:a', # a: _should_ show up if we don't filter
      'common/a:foo',
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      targets=self.targets('common/::')
    )

  def test_filter_regex(self):
    self.assert_console_output(
      'common/a:a',
      'common/a:foo',
      'common/b:b',
      'common/b:foo',
      'common/c:c',
      'common/c:foo',
      args=['--test-regex=^common'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a:foo',
      'common/b:foo',
      'common/c:foo',
      'overlaps:one',
      'overlaps:two',
      'overlaps:three',
      'overlaps:foo',
      args=['--test-regex=+foo,^overlaps'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'overlaps:one',
      'overlaps:two',
      'overlaps:three',
      args=['--test-regex=-^common,foo$'],
      targets=self.targets('::')
    )
