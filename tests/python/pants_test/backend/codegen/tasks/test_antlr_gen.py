# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import time
from textwrap import dedent

from twitter.common.dirutil.fileset import Fileset

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.tasks.antlr_gen import AntlrGen
from pants.base.address import Address
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class AntlrGenTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return AntlrGen

  @property
  def alias_groups(self):
    return super(AntlrGenTest, self).alias_groups.merge(BuildFileAliases(
      targets={
        'java_antlr_library': JavaAntlrLibrary,
      },
    ))

  PARTS = {'srcroot': 'testprojects/src/antlr',
           'dir': 'this/is/a/directory',
           'name': 'smoke',
           'prefix': 'SMOKE'}

  VERSIONS = {'3', '4'}

  PACKAGE_RE = re.compile(r'^\s*package\s+(?P<package_name>[^\s]+)\s*;\s*$')

  BUILDFILE = '{srcroot}/{dir}/BUILD'.format(**PARTS)

  def setUp(self):
    super(AntlrGenTest, self).setUp()

    SourceRoot.register('{srcroot}'.format(**self.PARTS), JavaAntlrLibrary)

    for ver in self.VERSIONS:
      self.create_file(
        relpath='{srcroot}/{dir}/{prefix}.g{version}'.format(version=ver, **self.PARTS),
        contents=dedent("""
        grammar {prefix};
        ////////////////////
        start  : letter EOF ;
        letter : LETTER ;
        ////////////////////
        fragment LETTER : 'a'..'z' | 'A'..'Z' ;
      """.format(**self.PARTS)))

  def create_context(self):
    # generate a context to contain the build graph for the input target.
    return self.context(target_roots=[self.get_antlr_target()])

  def get_antlr_target(self):
    return self.target('{srcroot}/{dir}:{name}'.format(**self.PARTS))

  def get_antlr_syn_target(self, task):
    target = self.get_antlr_target()
    target_workdir = task.codegen_workdir(target)
    syn_address = Address(os.path.relpath(target_workdir, get_buildroot()), target.id)
    return task.context.build_graph.get_target(syn_address)

  def execute_antlr_test(self, expected_package):
    context = self.create_context()
    task = self.execute(context)

    # get the synthetic target from the private graph
    task_outdir = os.path.join(task.workdir, 'isolated', self.get_antlr_target().id)

    # verify that the synthetic target's list of sources match what are actually created
    def re_relativize(p):
      """Take a path relative to task_outdir, and make it relative to the build_root"""
      return os.path.relpath(os.path.join(task_outdir, p), self.build_root)

    actual_sources = [re_relativize(s) for s in Fileset.rglobs('*.java', root=task_outdir)]
    expected_sources = self.get_antlr_syn_target(task).sources_relative_to_buildroot()
    self.assertEquals(set(expected_sources), set(actual_sources))

    # and that the synthetic target has a valid source root and the generated sources have the
    # expected java package
    def get_package(path):
      with open(path) as fp:
        for line in fp:
          match = self.PACKAGE_RE.match(line)
          if match:
            return match.group('package_name')
        return None

    syn_target = self.get_antlr_syn_target(task)
    for source in syn_target.sources_relative_to_source_root():
      source_path = os.path.join(task_outdir, source)
      self.assertTrue(os.path.isfile(source_path),
                      "{0} is not the source root for {1}".format(task_outdir, source))
      self.assertEqual(expected_package, get_package(source_path))

      self.assertIn(syn_target, context.targets())

  def test_explicit_package_v3(self):
    self._test_explicit_package(None, '3')

  def test_explicit_package_v4(self):
    self._test_explicit_package('this.is.a.package', '4')

  def _test_explicit_package(self, expected_package, version):
    self.add_to_build_file(self.BUILDFILE, dedent("""
      java_antlr_library(
        name='{name}',
        compiler='antlr{version}',
        package='this.is.a.package',
        sources=['{prefix}.g{version}'],
      )
    """.format(version=version, **self.PARTS)))

    self.execute_antlr_test(expected_package)

  def test_derived_package_v3(self):
    self._test_derived_package(None, '3')

  def test_derived_package_v4(self):
    self._test_derived_package(self.PARTS['dir'].replace('/', '.'), '4')

  def _test_derived_package(self, expected_package, version):
    self.add_to_build_file(self.BUILDFILE, dedent("""
      java_antlr_library(
        name='{name}',
        compiler='antlr{version}',
        sources=['{prefix}.g{version}'],
      )
    """.format(version=version, **self.PARTS)))

    self.execute_antlr_test(expected_package)

  def test_derived_package_invalid_v4(self):
    self.create_file(relpath='{srcroot}/{dir}/sub/not_read.g4'.format(**self.PARTS),
                     contents='// does not matter')

    self.add_to_build_file(self.BUILDFILE, dedent("""
      java_antlr_library(
        name='{name}',
        compiler='antlr4',
        sources=['{prefix}.g4', 'sub/not_read.g4'],
      )
    """.format(**self.PARTS)))

    with self.assertRaisesRegexp(TaskError, r'.*Antlr sources in multiple directories.*'):
      self.execute(self.create_context())

  def test_generated_target_fingerprint_stable_v3(self):
    self._test_generated_target_fingerprint_stable('3')

  def test_generated_target_fingerprint_stable_v4(self):
    self._test_generated_target_fingerprint_stable('4')

  def _test_generated_target_fingerprint_stable(self, version):

    def execute_and_get_synthetic_target_hash():
      # Rerun setUp() to clear up the build graph of injected synthetic targets.
      self.setUp()
      self.add_to_build_file(self.BUILDFILE, dedent("""
        java_antlr_library(
          name='{name}',
          compiler='antlr{version}',
          sources=['{prefix}.g{version}'],
        )
      """.format(version=version, **self.PARTS)))
      context = self.create_context()
      task = self.execute(context)
      return self.get_antlr_syn_target(task).transitive_invalidation_hash()

    fp1 = execute_and_get_synthetic_target_hash()
    # Sleeps 1 second to ensure the timestamp in sources generated by antlr is different.
    time.sleep(1)
    fp2 = execute_and_get_synthetic_target_hash()
    self.assertEqual(fp1, fp2,
        'Hash of generated synthetic target is not stable. {} != {}'.format(fp1, fp2))
