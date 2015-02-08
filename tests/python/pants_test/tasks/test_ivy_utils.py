# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import xml.etree.ElementTree as ET
from textwrap import dedent

from mock import Mock

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.ivy_utils import IvyModuleRef, IvyUtils
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.exclude import Exclude
from pants.util.contextutil import temporary_file_path
from pants_test.base_test import BaseTest


class IvyUtilsTestBase(BaseTest):
  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())


class IvyUtilsGenerateIvyTest(IvyUtilsTestBase):

  # TODO(John Sirois): increase coverage.
  # Some examples:
  # + multiple confs - via with_sources and with_docs for example
  # + excludes
  # + classifiers
  # + with_artifact

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
              provides=artifact('{org}', '{name}', repo=Repository()),
              sources=['z.java'],
            )
        """.format(org=self.b_org, name=self.b_name)))

    self.a = self.target('src/java/targets:a')
    self.b = self.target('src/java/targets:b')
    context = self.context()

  def test_exclude_exported(self):
    _, excludes = IvyUtils.calculate_classpath([self.b])
    self.assertEqual(excludes, set([Exclude(org=self.b_org, name=self.b_name)]))

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

  def test_resove_conflict(self):
    v1 = Mock()
    v1.force = False
    v1.rev ="1"

    v1_force = Mock()
    v1_force.force = True
    v1_force.rev = "1"

    v2 = Mock()
    v2.force = False
    v2.rev = "2"

    # If neither version is forced, use the latest version
    self.assertIs(v2, IvyUtils._resolve_conflict(v1, v2))
    self.assertIs(v2, IvyUtils._resolve_conflict(v2, v1))

    # If an earlier version is forced, use the forced version
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v1_force, v2))
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v2, v1_force))

    # If the same version is forced, use the forced version
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v1, v1_force))
    self.assertIs(v1_force, IvyUtils._resolve_conflict(v1_force, v1))

  def test_does_not_visit_diamond_dep_twice(self):
    ivy_info = self.parse_ivy_report('tests/python/pants_test/tasks/ivy_utils_resources/report_with_diamond.xml')

    ref = IvyModuleRef("toplevel", "toplevelmodule", "latest")
    seen = set()
    def collector(r):
      self.assertNotIn(r, seen)
      seen.add(r)
      return set([r])

    result = ivy_info.traverse_dependency_graph(ref, collector)

    self.assertEqual(
          {
            IvyModuleRef("toplevel", "toplevelmodule", "latest"),
            IvyModuleRef(org='org1', name='name1', rev='0.0.1'),
            IvyModuleRef(org='org2', name='name2', rev='0.0.1'),
            IvyModuleRef(org='org3', name='name3', rev='0.0.1')
          },
          result)

  def test_does_not_follow_cycle(self):
    ivy_info = self.parse_ivy_report('tests/python/pants_test/tasks/ivy_utils_resources/report_with_cycle.xml')

    ref = IvyModuleRef("toplevel", "toplevelmodule", "latest")
    seen = set()
    def collector(r):
      self.assertNotIn(r, seen)
      seen.add(r)
      return set([r])

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
    ivy_info = self.parse_ivy_report('tests/python/pants_test/tasks/ivy_utils_resources/report_with_diamond.xml')

    ref = IvyModuleRef(org='org1', name='name1', rev='0.0.1')
    def collector(r):
      return set([r])

    memo = dict()
    result1 = ivy_info.traverse_dependency_graph(ref, collector, memo=memo)
    result2 = ivy_info.traverse_dependency_graph(ref, collector, memo=memo)

    self.assertIs(result1, result2)
    self.assertEqual(
          {
            IvyModuleRef(org='org1', name='name1', rev='0.0.1'),
            IvyModuleRef(org='org2', name='name2', rev='0.0.1'),
            IvyModuleRef(org='org3', name='name3', rev='0.0.1')
          },
          result1)

  def parse_ivy_report(self, path):
    ivy_info = IvyUtils._parse_xml_report(path)
    self.assertIsNotNone(ivy_info)
    return ivy_info

  def find_single(self, elem, xpath):
    results = list(elem.findall(xpath))
    self.assertEqual(1, len(results))
    return results[0]

  def assert_attributes(self, elem, **kwargs):
    self.assertEqual(dict(**kwargs), dict(elem.attrib))
