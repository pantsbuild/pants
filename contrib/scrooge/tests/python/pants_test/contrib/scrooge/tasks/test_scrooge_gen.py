# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

import pytest
from mock import MagicMock, patch
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.goal.context import Context
from pants.util.dirutil import safe_rmtree
from pants_test.base.context_utils import create_options
from pants_test.tasks.task_test_base import TaskTestBase
from twitter.common.collections import OrderedSet

from pants.contrib.scrooge.tasks.scrooge_gen import ScroogeGen


# TODO (tdesai) Issue-240: Use JvmToolTaskTestBase for ScroogeGenTest
class ScroogeGenTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return ScroogeGen

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'java_thrift_library': JavaThriftLibrary})

  def setUp(self):
    super(ScroogeGenTest, self).setUp()
    self.task_outdir = os.path.join(self.build_root, 'scrooge', 'gen-java')

  def tearDown(self):
    super(ScroogeGenTest, self).tearDown()
    safe_rmtree(self.task_outdir)

  def test_defaults(self):
    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='one',
        sources=[],
        dependencies=[':one'],
      )
    '''))
    target = self.target('test_validate:one')
    ScroogeGen._validate([target])
    self.assertEquals('sync', target.rpc_style)
    self.assertEquals('thrift', target.compiler)
    self.assertEquals('java', target.language)

  def test_invalid_value(self):
    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='one',
        sources=[],
        rpc_style='xyz',
        dependencies=[':one'],
      )
    '''))
    with pytest.raises(TargetDefinitionException):
      self.target('test_validate:one')

  def test_validate(self):
    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='one',
        compiler='thrift',
        language='scala',
        rpc_style='ostrich',
        sources=[],
        dependencies=[],
      )
    '''))

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='two',
        language='scala',
        rpc_style='ostrich',
        sources=[],
        dependencies=[':one'],
      )
    '''))

    self.add_to_build_file('test_validate', dedent('''
      java_thrift_library(name='three',
        sources=[],
        dependencies=[':one'],
        rpc_style='finagle',
        language='scala',
      )
    '''))

    target = self.target('test_validate:one')
    ScroogeGen._validate([target])
    self.assertEquals('ostrich', target.rpc_style)
    self.assertEquals('thrift', target.compiler)
    self.assertEquals('scala', target.language)

    target = self.target('test_validate:two')
    ScroogeGen._validate([target])
    self.assertEquals('ostrich', target.rpc_style)
    self.assertEquals('thrift', target.compiler)
    self.assertEquals('scala', target.language)

    with pytest.raises(TaskError):
      ScroogeGen._validate([self.target('test_validate:three')])

  def test_smoke(self):
    contents = dedent('''namespace java org.pantsbuild.example
      struct Example {
      1: optional i64 number
      }
    ''')

    self.create_file(relpath='test_smoke/a.thrift', contents=contents)
    self.add_to_build_file('test_smoke', dedent('''
      java_thrift_library(name='a',
        sources=['a.thrift'],
        dependencies=[],
        compiler='scrooge',
        language='scala',
        rpc_style='finagle'
      )
    '''))

    target = self.target('test_smoke:a')
    context = self.context(target_roots=[target])
    task = self.create_task(context)

    with patch('pants.contrib.scrooge.tasks.scrooge_gen.calculate_services'):
      task._outdir = MagicMock()
      task._outdir.return_value = self.task_outdir

      task.gen = MagicMock()
      sources = [os.path.join(self.task_outdir, 'org/pantsbuild/example/Example.scala')]
      task.gen.return_value = {'test_smoke/a.thrift': sources}

      saved_add_new_target = Context.add_new_target
      try:
        Context.add_new_target = MagicMock()
        task.execute()
        relative_task_outdir = os.path.relpath(self.task_outdir, get_buildroot())
        spec = '{spec_path}:{name}'.format(spec_path=relative_task_outdir, name='test_smoke.a')
        address = SyntheticAddress.parse(spec=spec)
        Context.add_new_target.assert_called_once_with(address,
                                                       ScalaLibrary,
                                                       sources=sources,
                                                       excludes=OrderedSet(),
                                                       dependencies=OrderedSet(),
                                                       provides=None,
                                                       derived_from=target)
      finally:
        Context.add_new_target = saved_add_new_target
