# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing
from StringIO import StringIO

import pants.backend.core.register as register_core
from pants.backend.core.tasks import builddictionary, reflect
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.python.register import build_file_aliases as register_python
from pants_test.tasks.test_base import BaseTest, TaskTest


OUTDIR = '/tmp/dist'

sample_ini_test_1 = """
[DEFAULT]
outdir: %s
""" % OUTDIR


class BuildBuildDictionaryTest(TaskTest):
  @classmethod
  def task_type(cls):
    return builddictionary.BuildBuildDictionary

  def execute_task(self, config=sample_ini_test_1):
    with closing(StringIO()) as output:
      task = self.prepare_task(config=config)
      task.execute()
      return output.getvalue()

  def test_builddict_empty(self):
    """Execution should be silent."""
    # We don't care _that_ much that execution be silent. Nice if at least
    # one test executes the task and doesn't explode, tho.
    self.assertEqual('', self.execute_task())


class ExtractedContentSanityTests(BaseTest):
  @property
  def alias_groups(self):
    return register_core.build_file_aliases().merge(register_jvm().merge(register_python()))

  def setUp(self):
    super(ExtractedContentSanityTests, self).setUp()
    self._syms = reflect.assemble_buildsyms(build_file_parser=self.build_file_parser)

  def test_sub_tocls(self):
    python_symbols = builddictionary.python_sub_tocl(self._syms).e

    # python_requirements goes through build_file_aliases.curry_context.
    # It's in the "Python" sub_tocl, but tenuously
    self.assertTrue('python_requirements' in python_symbols)

    # Some less-tenuous sanity checks
    for sym in ['python_library', 'python_tests']:
      self.assertTrue(sym in python_symbols)

    jvm_symbols = builddictionary.jvm_sub_tocl(self._syms).e
    for sym in ['java_library', 'scala_library']:
      self.assertTrue(sym in jvm_symbols)

  def test_goals_ref_does_not_crash(self):
    # Invoke reflect.* functions used in generating Goals Reference.
    # In this test context, goals is probably empty, so register some:
    register_core.register_goals()
    goals = reflect.gen_tasks_goals_reference_data()
    self.assertGreater(len(goals), 10,
                       'Detected 10 or fewer core goals?!')
    glopts = reflect.gen_goals_glopts_reference_data()
    self.assertGreater(len(glopts.options), 10,
                       'Detected 10 or fewer global CLI options?!')
