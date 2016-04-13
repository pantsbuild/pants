# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import xml.etree.ElementTree as ET
from collections import namedtuple
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.jvm.ivy_utils import (FrozenResolution, IvyFetchStep, IvyInfo, IvyModule,
                                         IvyModuleRef, IvyResolveMappingError, IvyResolveResult,
                                         IvyResolveStep, IvyUtils)
from pants.backend.jvm.jar_dependency_utils import M2Coordinate
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.register import build_file_aliases as register_core
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.contextutil import temporary_dir, temporary_file, temporary_file_path
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import subsystem_instance


def coord(org, name, classifier=None, rev=None, ext=None):
  rev = rev or '0.0.1'
  return M2Coordinate(org=org, name=name, rev=rev, classifier=classifier, ext=ext)


def return_resolve_result_missing_artifacts(*args, **kwargs):
  return namedtuple('mock_resolve', ['all_linked_artifacts_exist'])(lambda: False)


def do_nothing(*args, **kwards):
  pass


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

  def test_excludes_are_generated(self):
    _, excludes = IvyUtils.calculate_classpath([self.e])
    self.assertSetEqual(excludes, {Exclude(org='commons-lang', name='commons-lang')})

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
      with subsystem_instance(JarDependencyManagement):
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

  def test_resolve_conflict_missing_versions(self):
    v1 = JarDependency('org.example', 'foo', None, force=False)
    v2 = JarDependency('org.example', 'foo', '2', force=False)
    self.assertIs(v2, IvyUtils._resolve_conflict(v1, v2))
    self.assertIs(v2, IvyUtils._resolve_conflict(v2, v1))

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

  def test_get_resolved_jars_for_coordinates(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_diamond.xml')

    resolved_jars = ivy_info.get_resolved_jars_for_coordinates([JarDependency(org='org1',
                                                                              name='name1',
                                                                              rev='0.0.1',
                                                                              classifier='tests')])

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

    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_resolve_to_other_version.xml')

    resolved_jars = ivy_info.get_resolved_jars_for_coordinates([JarDependency(org='org1',
                                                                              name='name1',
                                                                              rev='0.0.1',
                                                                              classifier='tests')])

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

  def test_retrieve_resolved_jars_with_coordinates_on_flat_fetch_resolve(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_flat_graph.xml')
    coordinates = [coord(org='org1', name='name1', classifier='tests', rev='0.0.1')]

    result = ivy_info.get_resolved_jars_for_coordinates(coordinates)

    self.assertEqual(coordinates, [r.coordinate for r in result])

  def test_retrieve_resolved_jars_with_coordinates_differing_on_version_on_flat_fetch_resolve(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_flat_graph.xml')
    coordinates = [coord(org='org2', name='name2', rev='0.0.0')]

    result = ivy_info.get_resolved_jars_for_coordinates(coordinates)

    self.assertEqual([coord(org='org2', name='name2', rev='0.0.1')],
                     [r.coordinate for r in result])

  def test_parse_fails_when_same_classifier_different_type(self):
    with self.assertRaises(IvyResolveMappingError):
      self.parse_ivy_report('ivy_utils_resources/report_with_same_classifier_different_type.xml')

  def find_single(self, elem, xpath):
    results = list(elem.findall(xpath))
    self.assertEqual(1, len(results))
    return results[0]

  def assert_attributes(self, elem, **kwargs):
    self.assertEqual(dict(**kwargs), dict(elem.attrib))

  def test_construct_and_load_symlink_map(self):
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
          result_classpath, result_map = IvyUtils.construct_and_load_symlink_map(symlink_dir,
                                                                                 mock_cache_dir,
                                                                                 input_path,
                                                                                 output_path)
          symlink_foo_path = os.path.join(symlink_dir, 'foo.jar')
          self.assertEquals([symlink_foo_path], result_classpath)
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
          result_classpath, result_map = IvyUtils.construct_and_load_symlink_map(symlink_dir,
                                                                                 mock_cache_dir,
                                                                                 input_path,
                                                                                 output_path)
          symlink_bar_path = os.path.join(symlink_dir, 'bar.jar')
          self.assertEquals(
            {
              os.path.realpath(foo_path): symlink_foo_path,
              os.path.realpath(bar_path): symlink_bar_path,
            },
            result_map)
          self.assertEquals([symlink_foo_path, symlink_bar_path], result_classpath)

          with open(output_path, 'r') as outpath:
            self.assertEquals(symlink_foo_path + os.pathsep + symlink_bar_path, outpath.readline())
          self.assertTrue(os.path.islink(symlink_foo_path))
          self.assertTrue(os.path.exists(symlink_foo_path))
          self.assertTrue(os.path.islink(symlink_bar_path))
          self.assertTrue(os.path.exists(symlink_bar_path))

          # Reverse the ordering and make sure order is preserved in the output path
          with open(input_path, 'w') as inpath:
            inpath.write(os.pathsep.join([bar_path, foo_path]))
          IvyUtils.construct_and_load_symlink_map(symlink_dir,
                                                  mock_cache_dir,
                                                  input_path,
                                                  output_path)
          with open(output_path, 'r') as outpath:
            self.assertEquals(symlink_bar_path + os.pathsep + symlink_foo_path, outpath.readline())

  def test_missing_ivy_report(self):
    self.set_options_for_scope(IvySubsystem.options_scope,
                               cache_dir='DOES_NOT_EXIST',
                               use_nailgun=False)

    # Hack to initialize Ivy subsystem
    self.context()

    with self.assertRaises(IvyUtils.IvyResolveReportError):
      IvyUtils.parse_xml_report('default', IvyUtils.xml_report_path('INVALID_CACHE_DIR',
                                                                    'INVALID_REPORT_UNIQUE_NAME',
                                                                    'default'))

  def parse_ivy_report(self, rel_path):
    path = os.path.join('tests/python/pants_test/backend/jvm/tasks', rel_path)
    ivy_info = IvyUtils.parse_xml_report(conf='default', path=path)
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

  def test_collects_classifiers(self):
    ivy_info = self.parse_ivy_report('ivy_utils_resources/report_with_multiple_classifiers.xml')

    ref = IvyModuleRef("toplevel", "toplevelmodule", "latest")

    def collector(r):
      x = ivy_info.modules_by_ref.get(r)
      if x:
        return {x}
      else:
        return set()

    result = ivy_info.traverse_dependency_graph(ref, collector, dict())

    self.assertEqual(
      {IvyModule(ref=IvyModuleRef(org='org1',
                                  name='name1',
                                  rev='0.0.1',
                                  classifier=None,
                                  ext=u'jar'),
                 artifact='ivy2cache_path/org1/name1.jar',
                 callers=(IvyModuleRef(org='toplevel',
                                       name='toplevelmodule',
                                       rev='latest',
                                       classifier=None,
                                       ext=u'jar'),)),
       IvyModule(ref=IvyModuleRef(org='org1',
                                  name='name1',
                                  rev='0.0.1',
                                  classifier='wut',
                                  ext=u'jar'),
                 artifact='ivy2cache_path/org1/name1-wut.jar',
                 callers=(IvyModuleRef(org='toplevel',
                                       name='toplevelmodule',
                                       rev='latest',
                                       classifier=None,
                                       ext=u'jar'),))},
      result)

  def test_fetch_ivy_xml_requests_url_for_dependency_containing_url(self):
    with temporary_dir() as temp_dir:
      ivyxml = os.path.join(temp_dir, 'ivy.xml')
      IvyUtils.generate_fetch_ivy([JarDependency('org-f', 'name-f', 'rev-f', url='an-url')],
                                  ivyxml,
                                  ('default',),
                                  'some-name')

      with open(ivyxml) as f:
        self.assertIn('an-url', f.read())

  def test_fetch_requests_classifiers(self):
    with temporary_dir() as temp_dir:
      ivyxml = os.path.join(temp_dir, 'ivy.xml')
      IvyUtils.generate_fetch_ivy([JarDependency('org-f', 'name-f', 'rev-f', classifier='a-classifier')],
                                  ivyxml,
                                  ('default',),
                                  'some-name')

      with open(ivyxml) as f:
        self.assertIn('a-classifier', f.read())

  def test_fetch_applies_mutable(self):
    with temporary_dir() as temp_dir:
      ivyxml = os.path.join(temp_dir, 'ivy.xml')
      IvyUtils.generate_fetch_ivy([JarDependency('org-f', 'name-f', 'rev-f', mutable=True)],
                                  ivyxml,
                                  ('default',),
                                  'some-name')

      with open(ivyxml) as f:
        self.assertIn('changing="true"', f.read())

  def test_resolve_ivy_xml_requests_classifiers(self):
    with temporary_dir() as temp_dir:
      ivyxml = os.path.join(temp_dir, 'ivy.xml')
      jar_dep = JarDependency('org-f', 'name-f', 'rev-f', classifier='a-classifier')
      IvyUtils.generate_ivy(
        [self.make_target('something', JarLibrary, jars=[jar_dep])],
        [jar_dep],
        excludes=[],
        ivyxml=ivyxml,
        confs=('default',),
        resolve_hash_name='some-name',
        jar_dep_manager=namedtuple('stub_jar_dep_manager', ['resolve_version_conflict'])(lambda x: x))

      with open(ivyxml) as f:
        self.assertIn('classifier="a-classifier', f.read())

  def test_ivy_resolve_report_copying_fails_when_report_is_missing(self):
    with temporary_dir() as dir:
      with self.assertRaises(IvyUtils.IvyError):
        IvyUtils._copy_ivy_reports({'default': os.path.join(dir, 'to-file')},
                                   ['default'], dir, 'another-hash-name')


class IvyUtilsResolveStepsTest(BaseTest):
  def test_if_not_all_symlinked_files_exist_after_successful_resolve_fail(self):
    resolve = IvyResolveStep(
      ['default'],
      'hash_name',
      None,
      False,
      'cache_dir',
      'workdir')

    # Stub resolving and creating the result, returning one missing artifacts.
    resolve._do_resolve = do_nothing
    resolve.load = return_resolve_result_missing_artifacts

    with self.assertRaises(IvyResolveMappingError):
      resolve.exec_and_load(None, None, [], None, None, None)

  def test_if_not_all_symlinked_files_exist_after_successful_fetch_fail(self):
    fetch = IvyFetchStep(['default'],
                         'hash_name',
                         False,
                         None,
                         'ivy_cache_dir', 'global_ivy_workdir')

    # Stub resolving and creating the result, returning one missing artifacts.
    fetch._do_fetch = do_nothing
    fetch._load_from_fetch = return_resolve_result_missing_artifacts

    with self.assertRaises(IvyResolveMappingError):
      fetch.exec_and_load(None, None, [], None, None, None)

  def test_missing_symlinked_jar_in_candidates(self):
    empty_symlink_map = {}
    result = IvyResolveResult(['non-existent-file-location'], empty_symlink_map, 'hash-name',
                              {'default':
                                 self.ivy_report_path('ivy_utils_resources/report_with_diamond.xml')
                               })
    with self.assertRaises(IvyResolveMappingError):
      list(result.resolved_jars_for_each_target('default',
                                                [self.make_target('t', JarLibrary,
                                                                  jars=[JarDependency('org1',
                                                                                      'name1')])
                                                 ]))

  def ivy_report_path(self, rel_path):
    return os.path.join('tests/python/pants_test/backend/jvm/tasks', rel_path)


class IvyFrozenResolutionTest(BaseTest):

  def test_spec_without_a_real_target(self):
    with temporary_file() as resolve_file:

      json.dump(
        {"default":{"coord_to_attrs":{}, "target_to_coords":{"non-existent-target":[]}}},
        resolve_file)
      resolve_file.close()

      with self.assertRaises(FrozenResolution.MissingTarget):
        FrozenResolution.load_from_file(resolve_file.name, [])
