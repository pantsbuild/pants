# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from twitter.common.dirutil import safe_mkdtemp, safe_rmtree

from pants.backend.core.tasks.check_exclusives import ExclusivesMapping
from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen
from pants_test.base_test import BaseTest


dummydoc = Jvmdoc(tool_name='dummydoc', product_type='dummydoc')


class DummyJvmdocGen(JvmdocGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    cls.generate_setup_parser(option_group, args, mkflag, dummydoc)

  def __init__(self, context, workdir):
    super(DummyJvmdocGen, self).__init__(context, workdir, dummydoc, None, True)

  def execute(self):
    self.generate_execute(lambda t: True, create_dummydoc_command)


def create_dummydoc_command(classpath, gendir, *targets):
  # here we need to test that we get the expected classpath
  None


options = {
  'DummyJvmdocGen_combined_opt': None,
  'DummyJvmdocGen_ignore_failure_opt': None,
  'DummyJvmdocGen_include_codegen_opt': None,
  'DummyJvmdocGen_open_opt': None,
  'DummyJvmdocGen_transitive_opt': None,
}

class JvmdocGenTest(BaseTest):
  """Test some base functionality in JvmdocGen."""

  def setUp(self):
    super(JvmdocGenTest, self).setUp()
    self.workdir = safe_mkdtemp()

    self.t1 = self.make_target('t1', exclusives={'foo': 'a'})
    # Force exclusive propagation on the targets.
    self.t1.get_all_exclusives()
    context = self.context(target_roots=[self.t1],
                           options=options)

    # Create the exclusives mapping.
    exclusives_mapping = ExclusivesMapping(context)
    exclusives_mapping._populate_target_maps(context.targets())
    exclusives_mapping.set_base_classpath_for_group('foo=a', ['baz'])
    context.products.safe_create_data('exclusives_groups', lambda: exclusives_mapping)

    self.task = DummyJvmdocGen(context, self.workdir)

  def tearDown(self):
    super(JvmdocGenTest, self).tearDown()
    safe_rmtree(self.workdir)

  def test_classpath(self):
    self.task.execute()
