# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from textwrap import dedent

from twitter.common.dirutil.fileset import Fileset

from pants.backend.codegen.tasks.antlr_gen import AntlrGen
from pants.base.address import SyntheticAddress
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class AntlrGenTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return AntlrGen

  PARTS = {'srcroot': 'testprojects/src/antlr',
           'dir': 'this/is/a/directory',
           'name': 'smoke',
           'prefix': 'SMOKE'}

  PACKAGE_RE = re.compile(r'^\s*package\s+(?P<package_name>[^\s]+)\s*;\s*$')

  def setUp(self):
    super(AntlrGenTest, self).setUp()
    self.create_file(relpath='{srcroot}/{dir}/{prefix}.g4'.format(**self.PARTS),
                     contents=dedent('''
      grammar {prefix};
      ////////////////////
      start  : letter EOF ;
      letter : LETTER ;
      ////////////////////
      fragment LETTER : [a-zA-Z] ;
    '''.format(**self.PARTS)))

  def create_context(self):
    # generate a context to contain the build graph for the input target, then execute
    antlr_target = self.target('{srcroot}/{dir}:{name}'.format(**self.PARTS))
    return self.context(target_roots=[antlr_target])

  def execute_antlr4_test(self, expected_package):
    context = self.create_context()
    task = self.execute(context)

    # get the synthetic target from the private graph
    task_outdir = os.path.join(task.workdir, 'antlr4', 'gen-java')
    syn_sourceroot = os.path.join(task_outdir, self.PARTS['srcroot'])
    syn_target_name = ('{srcroot}/{dir}.{name}'.format(**self.PARTS)).replace('/', '.')
    syn_address = SyntheticAddress(spec_path=os.path.relpath(syn_sourceroot, self.build_root),
                                   target_name=syn_target_name)
    syn_target = context.build_graph.get_target(syn_address)

    # verify that the synthetic target's list of sources match what are actually created
    def re_relativize(p):
      """Take a path relative to task_outdir, and make it relative to the build_root"""
      return os.path.relpath(os.path.join(task_outdir, p), self.build_root)

    actual_sources = [re_relativize(s) for s in Fileset.rglobs('*.java', root=task_outdir)]
    self.assertEquals(set(syn_target.sources_relative_to_buildroot()), set(actual_sources))

    # and that the synthetic target has a valid source root and the generated sources have the
    # expected java package
    def get_package(path):
      with open(path) as fp:
        for line in fp:
          match = self.PACKAGE_RE.match(line)
          if match:
            return match.group('package_name')
        return None

    for source in syn_target.sources_relative_to_source_root():
      source_path = os.path.join(syn_sourceroot, source)
      self.assertTrue(os.path.isfile(source_path),
                      "{0} is not the source root for {1}".format(syn_sourceroot, source))
      self.assertEqual(expected_package, get_package(source_path))

      self.assertIn(syn_target, context.targets())

  def test_explicit_package(self):
    self.add_to_build_file('{srcroot}/{dir}/BUILD'.format(**self.PARTS), dedent('''
      java_antlr_library(
        name='{name}',
        compiler='antlr4',
        package='this.is.a.package',
        sources=['{prefix}.g4'],
      )
    '''.format(**self.PARTS)))

    self.execute_antlr4_test('this.is.a.package')

  def test_derived_package(self):
    self.add_to_build_file('{srcroot}/{dir}/BUILD'.format(**self.PARTS), dedent('''
      java_antlr_library(
        name='{name}',
        compiler='antlr4',
        sources=['{prefix}.g4'],
      )
    '''.format(**self.PARTS)))

    self.execute_antlr4_test(self.PARTS['dir'].replace('/', '.'))

  def test_derived_package_invalid(self):
    self.create_file(relpath='{srcroot}/{dir}/sub/not_read.g4'.format(**self.PARTS),
                     contents='// does not matter')

    self.add_to_build_file('{srcroot}/{dir}/BUILD'.format(**self.PARTS), dedent('''
      java_antlr_library(
        name='{name}',
        compiler='antlr4',
        sources=['{prefix}.g4', 'sub/not_read.g4'],
      )
    '''.format(**self.PARTS)))

    with self.assertRaises(AntlrGen.AmbiguousPackageError):
      self.execute(self.create_context())
