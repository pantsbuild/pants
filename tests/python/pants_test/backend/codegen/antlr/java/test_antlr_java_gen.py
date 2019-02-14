# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import time
from builtins import open
from textwrap import dedent

from twitter.common.dirutil.fileset import Fileset

from pants.backend.codegen.antlr.java.antlr_java_gen import AntlrJavaGen
from pants.backend.codegen.antlr.java.java_antlr_library import JavaAntlrLibrary
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.util.dirutil import safe_mkdtemp
from pants.util.objects import datatype
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class DummyVersionedTarget(datatype(['target', 'results_dir'])):
  @property
  def current_results_dir(self):
    return self.results_dir


class AntlrJavaGenTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return AntlrJavaGen

  @classmethod
  def alias_groups(cls):
    return super(AntlrJavaGenTest, cls).alias_groups().merge(BuildFileAliases(
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
    super(AntlrJavaGenTest, self).setUp()

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

  def execute_antlr_test(self, expected_package, target_workdir_fun=None):
    target = self.get_antlr_target()
    context = self.create_context()
    task = self.prepare_execute(context)
    target_workdir_fun = target_workdir_fun or (lambda x: safe_mkdtemp(dir=x))
    # Do not use task.workdir here, because when we calculating hash for synthetic target
    # we need persistent source paths in terms of relative position to build root.
    target_workdir = target_workdir_fun(self.build_root)
    vt = DummyVersionedTarget(target, target_workdir)

    # Generate code, then create a synthetic target.
    task.execute_codegen(target, target_workdir)
    sources = task._capture_sources((vt,))[0]
    syn_target = task._inject_synthetic_target(vt, sources)

    actual_sources = [s for s in Fileset.rglobs('*.java', root=target_workdir)]
    expected_sources = syn_target.sources_relative_to_source_root()
    self.assertEqual(set(expected_sources), set(actual_sources))

    # Check that the synthetic target has a valid source root and the generated sources have the
    # expected java package
    def get_package(path):
      with open(path, 'r') as fp:
        for line in fp:
          match = self.PACKAGE_RE.match(line)
          if match:
            return match.group('package_name')
        return None

    for source in syn_target.sources_relative_to_source_root():
      source_path = os.path.join(target_workdir, source)
      self.assertTrue(os.path.isfile(source_path),
                      "{0} is not the source root for {1}".format(target_workdir, source))
      self.assertEqual(expected_package, get_package(source_path))

      self.assertIn(syn_target, context.targets())

    # Check that the output file locations match the package
    if expected_package is not None:
      expected_path_prefix = expected_package.replace('.', os.path.sep) + os.path.sep
      for source in syn_target.sources_relative_to_source_root():
        self.assertTrue(source.startswith(expected_path_prefix),
                        "{0} does not start with {1}".format(source, expected_path_prefix))

    # Check that empty directories have been removed
    for root, dirs, files in os.walk(target_workdir):
      for d in dirs:
        full_dir = os.path.join(root, d)
        self.assertTrue(os.listdir(full_dir),
                         "Empty directories should have been removed ({0})".format(full_dir))

    return syn_target

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
    self._test_generated_target_fingerprint_stable('3', None)

  def test_generated_target_fingerprint_stable_v4(self):
    self._test_generated_target_fingerprint_stable('4', self.PARTS['dir'].replace('/', '.'))

  def _test_generated_target_fingerprint_stable(self, version, package):
    self.add_to_build_file(self.BUILDFILE, dedent("""
      java_antlr_library(
        name='{name}',
        compiler='antlr{version}',
        sources=['{prefix}.g{version}'],
      )
    """.format(version=version, **self.PARTS)))

    def execute_and_get_synthetic_target_hash():
      # Recreate the build graph.
      self.reset_build_graph()
      # Use a stable workdir for both builds.
      target_workdir_fun = lambda root: os.path.join(root, 'stable')
      syn_target = self.execute_antlr_test(package, target_workdir_fun=target_workdir_fun)
      return syn_target.transitive_invalidation_hash()

    fp1 = execute_and_get_synthetic_target_hash()
    # Sleeps 1 second to ensure the timestamp in sources generated by antlr is different.
    time.sleep(1)
    fp2 = execute_and_get_synthetic_target_hash()
    self.assertEqual(fp1, fp2,
        'Hash of generated synthetic target is not stable. {} != {}'.format(fp1, fp2))
