# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.tasks.filter import Filter
from pants.tasks.test_base import ConsoleTaskTest


class BaseFilterTest(ConsoleTaskTest):
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
  @classmethod
  def setUpClass(cls):
    super(FilterTest, cls).setUpClass()

    requirement_injected = set()

    def create_target(path, name, *deps):
      if path not in requirement_injected:
        cls.create_target(path, "python_requirement('foo')")
        requirement_injected.add(path)
      all_deps = ["pants('%s')" % dep for dep in deps] + ["pants(':foo')"]
      cls.create_target(path, dedent('''
          python_library(name='%s',
            dependencies=[%s]
          )
          ''' % (name, ','.join(all_deps))))

    create_target('common/a', 'a')
    create_target('common/b', 'b')
    create_target('common/c', 'c')
    create_target('overlaps', 'one', 'common/a', 'common/b')
    create_target('overlaps', 'two', 'common/a', 'common/c')
    create_target('overlaps', 'three', 'common/a', 'overlaps:one')

  def test_roots(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      targets=self.targets('common/::'),
      extra_targets=self.targets('overlaps/::')
    )

  def test_nodups(self):
    targets = [self.target('common/b')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'common/b/BUILD:b',
      targets=targets
    )

  def test_no_filters(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      'overlaps/BUILD:foo',
      targets=self.targets('::')
    )

  def test_filter_type(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/b/BUILD:b',
      'common/c/BUILD:c',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-type=python_library'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:foo',
      'common/b/BUILD:foo',
      'common/c/BUILD:foo',
      'overlaps/BUILD:foo',
      args=['--test-type=-python_library'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      'overlaps/BUILD:foo',
      args=['--test-type=PythonRequirement,pants.targets.python_library.PythonLibrary'],
      targets=self.targets('::')
    )

  def test_filter_target(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'overlaps/BUILD:foo',
      args=['--test-target=common/a,overlaps/:foo'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-target=-common/a/BUILD:a,overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

  def test_filter_ancestor(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:foo',
      args=['--test-ancestor=overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-ancestor=-overlaps:one,overlaps:foo'],
      targets=self.targets('::')
    )

  def test_filter_regex(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/a/BUILD:foo',
      'common/b/BUILD:b',
      'common/b/BUILD:foo',
      'common/c/BUILD:c',
      'common/c/BUILD:foo',
      args=['--test-regex=^common'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'common/a/BUILD:foo',
      'common/b/BUILD:foo',
      'common/c/BUILD:foo',
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      'overlaps/BUILD:foo',
      args=['--test-regex=+foo,^overlaps'],
      targets=self.targets('::')
    )

    self.assert_console_output(
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      args=['--test-regex=-^common,foo$'],
      targets=self.targets('::')
    )
