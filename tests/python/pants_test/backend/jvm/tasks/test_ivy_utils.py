# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import xml.etree.ElementTree as ET
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.ivy_utils import (IvyInfo, IvyModule, IvyModuleRef, IvyResolveMappingError,
                                         IvyUtils)
from pants.backend.jvm.jar_dependency_utils import M2Coordinate
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.contextutil import temporary_dir, temporary_file_path
from pants_test.base_test import BaseTest


def coord(org, name, classifier=None, rev=None, ext=None):
  rev = rev or '0.0.1'
  return M2Coordinate(org=org, name=name, rev=rev, classifier=classifier, ext=ext)


class IvyUtilsTestBase(BaseTest):

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())


class IvyUtilsGenerateIvyTest(IvyUtilsTestBase):

  def setUp(self):
    super(IvyUtilsGenerateIvyTest, self).setUp()

    self.add_to_build_file('src/java/targets',
        dedent("""
            jar_library(
              name='a',
              jars=[
                jar('org1', 'name1', 'rev1'),
                jar('org2', 'name2', 'rev2', force=True),
              ],
            )
        """))

    self.b_org = 'com.example'
    self.b_name = 'b'
    self.add_to_build_file('src/java/targets',
        dedent("""
            java_library(
              name='b',
              dependencies=[':a'],
              provides=artifact('{org}', '{name}', repo=repository()),
              sources=['z.java'],
            )
        """.format(org=self.b_org, name=self.b_name)))

    self.add_to_build_file('3rdparty',
        dedent("""
            jar_library(
              name='example-morx',
              jars = [
                jar(org='commons-lang', name='commons-lang', rev='2.5', classifier='morx'),
              ]
            )
            jar_library(
              name='example-fleem',
              jars = [
                jar(org='commons-lang', name='commons-lang', rev='2.5', classifier='fleem'),
              ]
            )
        """))

    self.add_to_build_file('src/java/targets',
        dedent("""
            java_library(
              name='c',
              dependencies=[
                '3rdparty:example-morx',
                '3rdparty:example-fleem',
              ],
              sources=['w.java'],
            )
        """.format(org=self.b_org, name=self.b_name)))

    self.add_to_build_file('src/java/targets',
        dedent("""
            java_library(
              name='e',
              dependencies=[
                '3rdparty:example-morx',
                '3rdparty:example-fleem',
              ],
              excludes=[exclude(org='commons-lang', name='commons-lang')],
              sources=['w.java'],
            )
        """.format(org=self.b_org, name=self.b_name)))

    self.a = self.target('src/java/targets:a')
    self.b = self.target('src/java/targets:b')
    self.c = self.target('src/java/targets:c')
    self.e = self.target('src/java/targets:e')

  def test_exclude_exported(self):
    jars, excludes = IvyUtils.calculate_classpath([self.b])
    for jar in jars:
      self.assertEqual(jar.excludes, (Exclude(self.b_org, self.b_name),))
    self.assertEqual(excludes, set())

  def test_exclude_exported_disabled_when_no_excludes_gathered(self):
    _, excludes = IvyUtils.calculate_classpath([self.b], gather_excludes=False)
    self.assertSetEqual(excludes, set())

  def test_excludes_generated_when_requested(self):
    _, excludes = IvyUtils.calculate_classpath([self.e], gather_excludes=True)
    self.assertSetEqual(excludes, {Exclude(org='commons-lang', name='commons-lang')})

  def test_excludes_empty_when_not_requested(self):
    _, excludes = IvyUtils.calculate_classpath([self.e], gather_excludes=False)
    self.assertSetEqual(excludes, set())

  def test_classifiers(self):
    jars, _ = IvyUtils.calculate_classpath([self.c])

    jars.sort(key=lambda jar: jar.classifier)

    self.assertEquals(['fleem', 'morx'], [jar.classifier for jar in jars])

  def test_module_ref_str_minus_classifier(self):
    module_ref = IvyModuleRef(org='org', name='name', rev='rev')
    self.assertEquals("IvyModuleRef(org:name:rev::jar)", str(module_ref))

  def test_force_override(self):
    jars = list(self.a.payload.jars)
    with temporary_file_path() as ivyxml:
      IvyUtils.generate_ivy([self.a], jars=jars, excludes=[], ivyxml=ivyxml, confs=['default'])

      doc = ET.parse(ivyxml).getroot()

      conf = self.find_single(doc, 'configurations/conf')
      self.assert_attributes(conf, name='default')

      dependencies = list(doc.findall('dependencies/dependency'))
      self.assertEqual(2, len(dependencies))

      dep1 = dependencies[0]
      self.assert_attributes(dep1, org='org1', name='name1', rev='rev1')
      conf = self.find_single(dep1, 'conf')
      self.assert_attributes(conf, name='default', mapped='default')

      dep2 = dependencies[1]
      self.assert_attributes(dep2, org='org2', name='name2', rev='rev2', force='true')
      conf = self.find_single(dep1, 'conf')
      self.assert_attributes(conf, name='default', mapped='default')

      override = self.find_single(doc, 'dependencies/override')
      self.assert_attributes(override, org='org2', module='name2', rev='rev2')

  def test_resove_conflict_no_conflicts(self):
    v1 = JarDependency('org.example', 'foo', '1', force=False)
    v1_force = JarDependency('org.example', 'foo', '1', force=True)
    v2 = JarDependency('org.example', 'foo', '2', force=False)

    # If neither version is forced, use the latest version.
    self.assertIs(v2, IvyUtils._resolve_conflict(v1, v2))
    self.assertIs(v2, IvyUtils._resolve_conflict(v2, v1))

    # If an earlier version is forced, use the forced version.
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v1_force, v2))
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v2, v1_force))

    # If the same version is forced, use the forced version.
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v1, v1_force))
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v1_force, v1))

    # If the same force is in play in multiple locations, allow it.
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v1_force, v1_force))

  def test_resolve_conflict_conflict(self):
    v1_force = JarDependency('org.example', 'foo', '1', force=True)
    v2_force = JarDependency('org.example', 'foo', '2', force=True)

    with self.assertRaises(IvyUtils.IvyResolveConflictingDepsError):
      IvyUtils._resolve_conflict(v1_force, v2_force)

    with self.assertRaises(IvyUtils.IvyResolveConflictingDepsError):
      IvyUtils._resolve_conflict(v2_force, v1_force)

  def test_get_resolved_jars_for_jar_library(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_diamond.xml')
    lib = self.make_target(spec=':org1-name1',
                           target_type=JarLibrary,
                           jars=[JarDependency(org='org1', name='name1', rev='0.0.1',
                                               classifier='tests')])

    resolved_jars = ivy_info.get_resolved_jars_for_jar_library(lib)

    expected = {'ivy2cache_path/org1/name1.jar': coord(org='org1', name='name1',
                                                       classifier='tests'),
                'ivy2cache_path/org2/name2.jar': coord(org='org2', name='name2'),
                'ivy2cache_path/org3/name3.tar.gz': coord(org='org3', name='name3', ext='tar.gz')}
    self.maxDiff = None
    coordinate_by_path = {rj.cache_path: rj.coordinate for rj in resolved_jars}
    self.assertEqual(expected, coordinate_by_path)

  def test_resolved_jars_with_different_version(self):
    # If a jar is resolved as a different version than the requested one, the coordinates of
    # the resolved jar should match the artifact, not the requested coordinates.
    lib = self.make_target(spec=':org1-name1',
                           target_type=JarLibrary,
                           jars=[
                             JarDependency(org='org1', name='name1',
                                           rev='0.0.1',
                                           classifier='tests')])

    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_resolve_to_other_version.xml')

    resolved_jars = ivy_info.get_resolved_jars_for_jar_library(lib)

    self.maxDiff = None
    self.assertEqual([coord(org='org1', name='name1',
                           classifier='tests',
                           rev='0.0.2')],
                     [jar.coordinate for jar in resolved_jars])

  def test_does_not_visit_diamond_dep_twice(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_diamond.xml')

    ref = IvyModuleRef("toplevel", "toplevelmodule", "latest")
    seen = set()

    def collector(r):
      self.assertNotIn(r, seen)
      seen.add(r)
      return {r}

    result = ivy_info.traverse_dependency_graph(ref, collector)

    self.assertEqual({IvyModuleRef("toplevel", "toplevelmodule", "latest"),
                      IvyModuleRef(org='org1', name='name1', rev='0.0.1', classifier='tests'),
                      IvyModuleRef(org='org2', name='name2', rev='0.0.1'),
                      IvyModuleRef(org='org3', name='name3', rev='0.0.1', ext='tar.gz')},
          result)

  def test_does_not_follow_cycle(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_cycle.xml')

    ref = IvyModuleRef("toplevel", "toplevelmodule", "latest")
    seen = set()

    def collector(r):
      self.assertNotIn(r, seen)
      seen.add(r)
      return {r}

    result = ivy_info.traverse_dependency_graph(ref, collector)

    self.assertEqual(
          {
            IvyModuleRef("toplevel", "toplevelmodule", "latest"),
            IvyModuleRef(org='org1', name='name1', rev='0.0.1'),
            IvyModuleRef(org='org2', name='name2', rev='0.0.1'),
            IvyModuleRef(org='org3', name='name3', rev='0.0.1')
          },
          result)

  def test_memo_reused_across_calls(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_diamond.xml')

    ref = IvyModuleRef(org='org1', name='name1', rev='0.0.1')

    def collector(r):
      return {r}

    memo = dict()
    result1 = ivy_info.traverse_dependency_graph(ref, collector, memo=memo)
    result2 = ivy_info.traverse_dependency_graph(ref, collector, memo=memo)

    self.assertIs(result1, result2)
    self.assertEqual(
          {
            IvyModuleRef(org='org1', name='name1', rev='0.0.1'),
            IvyModuleRef(org='org2', name='name2', rev='0.0.1'),
            IvyModuleRef(org='org3', name='name3', rev='0.0.1', ext='tar.gz')
          },
          result1)

  def test_parse_fails_when_same_classifier_different_type(self):
    with self.assertRaises(IvyResolveMappingError):
      self.parse_ivy_report('ivy_utils_resources/report_with_same_classifier_different_type.xml')

  def find_single(self, elem, xpath):
    results = list(elem.findall(xpath))
    self.assertEqual(1, len(results))
    return results[0]

  def assert_attributes(self, elem, **kwargs):
    self.assertEqual(dict(**kwargs), dict(elem.attrib))

  def test_symlink_cachepath(self):
    self.maxDiff = None
    with temporary_dir() as mock_cache_dir:
      with temporary_dir() as symlink_dir:
        with temporary_dir() as classpath_dir:
          input_path = os.path.join(classpath_dir, 'inpath')
          output_path = os.path.join(classpath_dir, 'classpath')
          foo_path = os.path.join(mock_cache_dir, 'foo.jar')
          with open(foo_path, 'w') as foo:
            foo.write("test jar contents")

          with open(input_path, 'w') as inpath:
            inpath.write(foo_path)
          result_map = IvyUtils.symlink_cachepath(mock_cache_dir, input_path, symlink_dir,
                                                  output_path)
          symlink_foo_path = os.path.join(symlink_dir, 'foo.jar')
          self.assertEquals(
            {
              os.path.realpath(foo_path): symlink_foo_path
            },
            result_map)
          with open(output_path, 'r') as outpath:
            self.assertEquals(symlink_foo_path, outpath.readline())
          self.assertTrue(os.path.islink(symlink_foo_path))
          self.assertTrue(os.path.exists(symlink_foo_path))

          # Now add an additional path to the existing map
          bar_path = os.path.join(mock_cache_dir, 'bar.jar')
          with open(bar_path, 'w') as bar:
            bar.write("test jar contents2")
          with open(input_path, 'w') as inpath:
            inpath.write(os.pathsep.join([foo_path, bar_path]))
          result_map = IvyUtils.symlink_cachepath(mock_cache_dir, input_path, symlink_dir,
                                                  output_path)
          symlink_bar_path = os.path.join(symlink_dir, 'bar.jar')
          self.assertEquals(
            {
              os.path.realpath(foo_path): symlink_foo_path,
              os.path.realpath(bar_path): symlink_bar_path,
            },
            result_map)
          with open(output_path, 'r') as outpath:
            self.assertEquals(symlink_foo_path + os.pathsep + symlink_bar_path, outpath.readline())
          self.assertTrue(os.path.islink(symlink_foo_path))
          self.assertTrue(os.path.exists(symlink_foo_path))
          self.assertTrue(os.path.islink(symlink_bar_path))
          self.assertTrue(os.path.exists(symlink_bar_path))

          # Reverse the ordering and make sure order is preserved in the output path
          with open(input_path, 'w') as inpath:
            inpath.write(os.pathsep.join([bar_path, foo_path]))
          IvyUtils.symlink_cachepath(mock_cache_dir, input_path, symlink_dir, output_path)
          with open(output_path, 'r') as outpath:
            self.assertEquals(symlink_bar_path + os.pathsep + symlink_foo_path, outpath.readline())

  def test_missing_ivy_report(self):
    self.set_options_for_scope(IvySubsystem.options_scope,
                               cache_dir='DOES_NOT_EXIST',
                               use_nailgun=False)

    # Hack to initialize Ivy subsystem
    self.context()

    with self.assertRaises(IvyUtils.IvyResolveReportError):
      IvyUtils.parse_xml_report('INVALID_CACHE_DIR', 'INVALID_REPORT_UNIQUE_NAME', 'default')

  def parse_ivy_report(self, rel_path):
    path = os.path.join('tests/python/pants_test/backend/jvm/tasks', rel_path)
    ivy_info = IvyUtils._parse_xml_report(conf='default', path=path)
    self.assertIsNotNone(ivy_info)
    return ivy_info

  def test_ivy_module_ref_cmp(self):
    self.assertEquals(
      IvyModuleRef('foo', 'bar', '1.2.3'), IvyModuleRef('foo', 'bar', '1.2.3'))
    self.assertTrue(
      IvyModuleRef('foo1', 'bar', '1.2.3') < IvyModuleRef('foo2', 'bar', '1.2.3'))
    self.assertTrue(
      IvyModuleRef('foo2', 'bar', '1.2.3') >IvyModuleRef('foo1', 'bar', '1.2.3'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar1', '1.2.3') < IvyModuleRef('foo', 'bar2', '1.2.3'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar2', '1.2.3') > IvyModuleRef('foo', 'bar1', '1.2.3'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.3') < IvyModuleRef('foo', 'bar', '1.2.4'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.4') > IvyModuleRef('foo', 'bar', '1.2.3'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.3', ext='jar') < IvyModuleRef('foo', 'bar', '1.2.3', ext='tgz'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.3', ext='tgz') > IvyModuleRef('foo', 'bar', '1.2.3', ext='jar'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.3', ext='jar', classifier='javadoc')
      < IvyModuleRef('foo', 'bar', '1.2.3', ext='jar', classifier='sources'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.3', ext='tgz', classifier='sources')
      > IvyModuleRef('foo', 'bar', '1.2.3', ext='jar', classifier='javadoc'))
    # make sure rev is sorted last
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.4', classifier='javadoc')
      < IvyModuleRef('foo', 'bar', '1.2.3', classifier='sources'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.3', classifier='sources')
      > IvyModuleRef('foo', 'bar', '1.2.4', classifier='javadoc'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.4', ext='jar')
      < IvyModuleRef('foo', 'bar', '1.2.3', ext='tgz'))
    self.assertTrue(
      IvyModuleRef('foo', 'bar', '1.2.3', ext='tgz')
      > IvyModuleRef('foo', 'bar', '1.2.4', ext='jar'))

  def test_traverse_dep_graph_sorted(self):
    """Make sure the modules are returned in a deterministic order by name"""

    def make_ref(org, name):
      return  IvyModuleRef(org=org, name=name, rev='1.0')

    ref1 = make_ref('foo', '1')
    ref2 = make_ref('foo', 'child1')
    ref3 = make_ref('foo', 'child2')
    ref4 = make_ref('foo', 'child3')
    ref5 = make_ref('foo', 'grandchild1')
    ref6 = make_ref('foo', 'grandchild2')

    module1 = IvyModule(ref1, '/foo', [])
    module2 = IvyModule(ref2, '/foo', [ref1])
    module3 = IvyModule(ref3, '/foo', [ref1])
    module4 = IvyModule(ref4, '/foo', [ref1])
    module5 = IvyModule(ref5, '/foo', [ref3])
    module6 = IvyModule(ref6, '/foo', [ref3])

    def assert_order(inputs):
      info = IvyInfo('default')
      for module in inputs:
        info.add_module(module)

      def collector(dep):
        return OrderedSet([dep])

      result = [ref for ref in info.traverse_dependency_graph(ref1, collector)]
      self.assertEquals([ref1, ref2, ref3, ref5, ref6, ref4],
                        result)
    # Make sure the order remains unchanged no matter what order we insert the into the structure
    assert_order([module1, module2, module3, module4, module5, module6])
    assert_order([module6, module5, module4, module3, module2, module1])
    assert_order([module5, module1, module2, module6,  module3, module4])
    assert_order([module6, module4, module3, module1 ,module2, module5])
    assert_order([module4, module2, module1, module3, module6, module5])
    assert_order([module4, module2, module5, module6, module1, module3])
