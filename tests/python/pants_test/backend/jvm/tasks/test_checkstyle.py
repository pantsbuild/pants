# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants_test.tasks.task_test_base import ensure_cached


class CheckstyleTest(NailgunTaskTestBase):
  """Tests for the class Checkstyle."""

  _RULE_XML_FILE_TAB_CHECKER = dedent("""
      <module name="FileTabCharacter"/>
  """)

  _RULE_XML_SUPPRESSION_FILTER = dedent("""
    <module name="SuppressionFilter">
      <property name="file" value="${checkstyle.suppression.file}"/>
    </module>
  """)

  _TEST_JAVA_SOURCE_WITH_NO_TAB = dedent("""
    public class HelloMain {
      public static void main(String[] args) throws IOException {
        System.out.println("A test.");
      }
    }
  """)

  _TEST_JAVA_SOURCE_WITH_TAB = dedent("""
    public class HelloMain {
      public static void main(String[] args) throws IOException {
        \tSystem.out.println("A test.");
      }
    }
  """)

  @classmethod
  def task_type(cls):
    return Checkstyle

  def _create_context(self, rules_xml=(), properties=None, target_roots=None):
    return self.context(
      options={
        self.options_scope: {
          'bootstrap_tools': ['//:checkstyle'],
          'configuration': self._create_config_file(rules_xml),
          'properties': properties or {},
        }
      },
      target_roots=target_roots)

  def _create_config_file(self, rules_xml=()):
    return self.create_file(
      relpath='coding_style.xml',
      contents=dedent(
        """<?xml version="1.0"?>
           <!DOCTYPE module PUBLIC
             "-//Puppy Crawl//DTD Check Configuration 1.3//EN"
             "http://www.puppycrawl.com/dtds/configuration_1_3.dtd">
           <module name="Checker">
             {rules_xml}
           </module>""".format(rules_xml='\n'.join(rules_xml))))

  def _create_suppression_file(self, suppresses_xml=()):
    return self.create_file(
      relpath='suppression.xml',
      contents=dedent(
        """<?xml version="1.0"?>
           <!DOCTYPE suppressions PUBLIC
             "-//Puppy Crawl//DTD Suppressions 1.1//EN"
            "http://www.puppycrawl.com/dtds/suppressions_1_1.dtd">
           <suppressions>
             {suppresses_xml}
           </suppressions>
        """.format(suppresses_xml='\n'.join(suppresses_xml))))

  def _create_target(self, name, test_java_source):
    rel_dir = os.path.join('src/java', name)
    self.create_file(relpath=os.path.join(rel_dir, '{name}.java'.format(name=name)),
                     contents=test_java_source)

    return self.make_target(Address(spec_path=rel_dir, target_name=name).spec,
                            JavaLibrary,
                            sources=['{}.java'.format(name)])

  #
  # Test section
  #
  @ensure_cached(Checkstyle, expected_num_artifacts=1)
  def test_single_rule_pass(self):
    no_tab = self._create_target('no_tab', self._TEST_JAVA_SOURCE_WITH_NO_TAB)
    context = self._create_context(rules_xml=[self._RULE_XML_FILE_TAB_CHECKER],
                                   target_roots=[no_tab])

    self.populate_runtime_classpath(context=context)
    self.execute(context)

  @ensure_cached(Checkstyle, expected_num_artifacts=0)
  def test_single_rule_fail(self):
    with_tab = self._create_target('with_tab', self._TEST_JAVA_SOURCE_WITH_TAB)
    context = self._create_context(rules_xml=[self._RULE_XML_FILE_TAB_CHECKER],
                                   target_roots=[with_tab])
    # add a tab in the source to trigger the tab check rule to fail.

    self.populate_runtime_classpath(context=context)
    with self.assertRaises(TaskError):
      self.execute(context)

  def test_suppressions(self):
    # For this test, we:
    # - add 3 java files, 2 with tabs, 1 without.
    # - add 2 suppression rules against those 2 java files with tabs,
    # so we can test the logic of suppression.

    suppression_file = self._create_suppression_file(
      [
        '<suppress files=".*with_tab_1\.java" checks=".*" />',
        '<suppress files=".*with_tab_2\.java" checks=".*" />',
      ])

    no_tab = self._create_target('no_tab', self._TEST_JAVA_SOURCE_WITH_NO_TAB)
    with_tab_1 = self._create_target('with_tab_1', self._TEST_JAVA_SOURCE_WITH_TAB)
    with_tab_2 = self._create_target('with_tab_2', self._TEST_JAVA_SOURCE_WITH_TAB)
    context = self._create_context(
      rules_xml=[
        self._RULE_XML_SUPPRESSION_FILTER,
        self._RULE_XML_FILE_TAB_CHECKER
      ],
      properties={
        'checkstyle.suppression.file': suppression_file,
      },
      target_roots=[no_tab, with_tab_1, with_tab_2])

    self.populate_runtime_classpath(context=context)
    self.execute(context)
