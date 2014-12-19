# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.base.address import BuildFileAddress
from pants.base.exceptions import TaskError
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class CheckstyleTest(NailgunTaskTestBase):
  """Tests for the class Checkstyle."""

  _RULE_XML_FILE_TAB_CHECKER = dedent('''
      <module name="FileTabCharacter"/>
  ''')

  _RULE_XML_SUPPRESSION_FILTER = dedent('''
    <module name="SuppressionFilter">
      <property name="file" value="${checkstyle.suppression.file}"/>
    </module>
  ''')

  _TEST_JAVA_SOURCE_WITH_NO_TAB = dedent('''
    public class HelloMain {
      public static void main(String[] args) throws IOException {
        System.out.println("A test.");
      }
    }
  ''')

  _TEST_JAVA_SOURCE_WITH_TAB = dedent('''
    public class HelloMain {
      public static void main(String[] args) throws IOException {
        \tSystem.out.println("A test.");
      }
    }
  ''')


  @classmethod
  def task_type(cls):
    return Checkstyle

  def _create_context(self, rules_xml=[], properties={}):
    return self.context(
      new_options={
        self.options_scope: {
          'bootstrap_tools': ['//:checkstyle'],
          'configuration': self._create_config_file(rules_xml),
          'properties': properties,
        }
      })

  def _create_config_file(self, rules_xml=[]):
    return self.create_file(
      relpath='coding_style.xml',
      contents=dedent(
        '''<?xml version="1.0"?>
           <!DOCTYPE module PUBLIC
             "-//Puppy Crawl//DTD Check Configuration 1.3//EN"
             "http://www.puppycrawl.com/dtds/configuration_1_3.dtd">
           <module name="Checker">
             {rules_xml}
           </module>'''.format(rules_xml='\n'.join(rules_xml))))

  def _create_suppression_file(self, suppresses_xml=[]):
    return self.create_file(
      relpath='suppression.xml',
      contents=dedent(
        '''<?xml version="1.0"?>
           <!DOCTYPE suppressions PUBLIC
             "-//Puppy Crawl//DTD Suppressions 1.1//EN"
            "http://www.puppycrawl.com/dtds/suppressions_1_1.dtd">
           <suppressions>
             {suppresses_xml}
           </suppressions>
        '''.format(suppresses_xml='\n'.join(suppresses_xml))))

  def _add_java_target_for_test(self, context, name, test_java_source):
    rel_dir = os.path.join('src/java', name)
    self.create_file(
      relpath=os.path.join(rel_dir, '{name}.java'.format(name=name)),
      contents=test_java_source)

    java_target_address = BuildFileAddress(
      self.add_to_build_file(
        os.path.join(rel_dir, 'BUILD'),
        'java_library(name="{name}", sources=["{name}.java"])'.format(name=name)),
      '{name}'.format(name=name))

    context.build_graph.inject_address_closure(java_target_address)
    java_target = context.build_graph.get_target(java_target_address)
    new_target_roots = [java_target]
    new_target_roots.extend(context.target_roots if context.target_roots else [])
    context.replace_targets(new_target_roots)

  #
  # Test section
  #
  def test_single_rule_pass(self):
    context = self._create_context(rules_xml=[self._RULE_XML_FILE_TAB_CHECKER])
    self._add_java_target_for_test(context, 'no_tab', self._TEST_JAVA_SOURCE_WITH_NO_TAB)
    self.populate_exclusive_groups(context=context)
    self.execute(context)

  def test_single_rule_fail(self):
    context = self._create_context(rules_xml=[self._RULE_XML_FILE_TAB_CHECKER])
    # add a tab in the source to trigger the tab check rule to fail.
    self._add_java_target_for_test(context, 'with_tab', self._TEST_JAVA_SOURCE_WITH_TAB)
    self.populate_exclusive_groups(context=context)
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

    context = self._create_context(
      rules_xml=[
        self._RULE_XML_SUPPRESSION_FILTER,
        self._RULE_XML_FILE_TAB_CHECKER
      ],
      properties={
        'checkstyle.suppression.file': suppression_file,
      })

    self._add_java_target_for_test(context, 'no_tab', self._TEST_JAVA_SOURCE_WITH_NO_TAB)
    self._add_java_target_for_test(context, 'with_tab_1', self._TEST_JAVA_SOURCE_WITH_TAB)
    self._add_java_target_for_test(context, 'with_tab_2', self._TEST_JAVA_SOURCE_WITH_TAB)

    self.populate_exclusive_groups(context=context)
    self.execute(context)
