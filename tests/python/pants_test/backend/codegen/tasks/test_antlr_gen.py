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
from pants.base.address import SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.source_root import SourceRoot
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class AntlrGenTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return AntlrGen

  @property
  def alias_groups(self):
    return super(AntlrGenTest, self).alias_groups.merge(BuildFileAliases.create(
      targets={
        'java_antlr_library': JavaAntlrLibrary,
      },
      context_aware_object_factories={
        'source_root': SourceRoot.factory,
      },
    ))

  PARTS = {'srcroot': 'testprojects/src/antlr',
           'dir': 'this/is/a/directory',
           'name': 'smoke',
           'prefix': 'SMOKE'}

  VERSIONS = {'3', '4'}

  PACKAGE_RE = re.compile(r'^\s*package\s+(?P<package_name>[^\s]+)\s*;\s*$')

  def setUp(self):
    super(AntlrGenTest, self).setUp()

    # There are some weird errors happening when caching is enabled on Antlr tests,
    # which is why the use of the artifact cache is disabled. These bugs do not surface
    # in Antlr integration tests (tasks/test_antlr_integration.py), which explicitly
    # test caching, because the issue lies within what the following tests expect
    # the SyntheticAddress of a target to be -- when caching is enabled, the expected
    # SyntheticAddress is always incorrect, however, it would seem that everything else
    # works just fine.
    #
    # Here's what happens without caching. In CodeGen->execute, within the self.invalidated
    # block, self.genlang is called for all of the invalidated targets. In AntlrGen->genlang,
    # the antlr classpath is computed with a call to self.tool_classpath(antlr_version).
    # This is where things get weird. This call has the strange side-effect of changing
    # each target.target_base: the sole test target prior to this call has a
    # target_base = "testprojects/src/antlr/this/is/a/directory", but _after_ this call,
    # it has a target_base = "testprojects/src/antlr". Note that self.tool_classpath does
    # not take the target as an argument, rather, somewhere deep down the callstack it is
    # muddling around with SourceRoot. Because target.target_base is used to compute a
    # SyntheticAddress, the tests rely on this seemingly magic change of target_base.
    #
    # When caching is enabled, the first test passes and caches the sole test target.
    # The rest of the tests run Antlr, but each one hits the cache, and thus none of the
    # targets are invalidated. Recall that self.genlang is called on invalidated targets,
    # so self.genlang is never called. Thus our sole test target's target_base is never
    # changed from "testprojects/src/antlr/this/is/a/directory" to "testprojects/src/antlr",
    # which causes the tests to fail, because the actual and expected SyntheticAddresses differ.
    self.disable_artifact_cache()

    self.add_to_build_file('BUILD', dedent("""
      source_root('{srcroot}', java_antlr_library)
    """.format(**self.PARTS)))

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
    # generate a context to contain the build graph for the input target, then execute
    antlr_target = self.target('{srcroot}/{dir}:{name}'.format(**self.PARTS))
    return self.context(target_roots=[antlr_target])

  def execute_antlr_test(self, expected_package, version):
    context = self.create_context()
    task = self.execute(context)

    # get the synthetic target from the private graph
    task_outdir = os.path.join(task.workdir, 'antlr' + version, 'gen-java')
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

  def test_explicit_package_v3(self):
    self._test_explicit_package(None, '3')

  def test_explicit_package_v4(self):
    self._test_explicit_package('this.is.a.package', '4')

  def _test_explicit_package(self, expected_package, version):
    self.add_to_build_file('{srcroot}/{dir}/BUILD'.format(**self.PARTS), dedent("""
      java_antlr_library(
        name='{name}',
        compiler='antlr{version}',
        package='this.is.a.package',
        sources=['{prefix}.g{version}'],
      )
    """.format(version=version, **self.PARTS)))

    self.execute_antlr_test(expected_package, version)

  def test_derived_package_v3(self):
    self._test_derived_package(None, '3')

  def test_derived_package_v4(self):
    self._test_derived_package(self.PARTS['dir'].replace('/', '.'), '4')

  def _test_derived_package(self, expected_package, version):
    self.add_to_build_file('{srcroot}/{dir}/BUILD'.format(**self.PARTS), dedent("""
      java_antlr_library(
        name='{name}',
        compiler='antlr{version}',
        sources=['{prefix}.g{version}'],
      )
    """.format(version=version, **self.PARTS)))

    self.execute_antlr_test(expected_package, version)

  def test_derived_package_invalid_v4(self):
    self.create_file(relpath='{srcroot}/{dir}/sub/not_read.g4'.format(**self.PARTS),
                     contents='// does not matter')

    self.add_to_build_file('{srcroot}/{dir}/BUILD'.format(**self.PARTS), dedent("""
      java_antlr_library(
        name='{name}',
        compiler='antlr4',
        sources=['{prefix}.g4', 'sub/not_read.g4'],
      )
    """.format(**self.PARTS)))

    with self.assertRaises(AntlrGen.AmbiguousPackageError):
      self.execute(self.create_context())

  def test_generated_target_fingerprint_stable_v3(self):
    self._test_generated_target_fingerprint_stable('3')

  def test_generated_target_fingerprint_stable_v4(self):
    self._test_generated_target_fingerprint_stable('4')

  def _test_generated_target_fingerprint_stable(self, version):

    def execute_and_get_synthetic_target_hash():
      # Rerun setUp() to clear up the build graph of injected synthetic targets.
      self.setUp()
      self.add_to_build_file('{srcroot}/{dir}/BUILD'.format(**self.PARTS), dedent("""
        java_antlr_library(
          name='{name}',
          compiler='antlr{version}',
          sources=['{prefix}.g{version}'],
        )
      """.format(version=version, **self.PARTS)))

      context = self.create_context()
      task = self.execute(context)

      # get the synthetic target from the private graph
      task_outdir = os.path.join(task.workdir, 'antlr' + version, 'gen-java')
      syn_sourceroot = os.path.join(task_outdir, self.PARTS['srcroot'])
      syn_target_name = ('{srcroot}/{dir}.{name}'.format(**self.PARTS)).replace('/', '.')
      syn_address = SyntheticAddress(spec_path=os.path.relpath(syn_sourceroot, self.build_root),
                                     target_name=syn_target_name)
      syn_target = context.build_graph.get_target(syn_address)
      return syn_target.transitive_invalidation_hash()

    fp1 = execute_and_get_synthetic_target_hash()
    # Sleeps 1 second to ensure the timestamp in sources generated by antlr is different.
    time.sleep(1)
    fp2 = execute_and_get_synthetic_target_hash()
    self.assertEqual(fp1, fp2,
        'Hash of generated synthetic target is not stable. {} != {}'.format(fp1, fp2))
