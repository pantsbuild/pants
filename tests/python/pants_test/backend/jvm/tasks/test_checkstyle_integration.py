# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import shutil
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_cached


class CheckstyleIntegrationTest(PantsRunIntegrationTest):

  def _create_config_file(self, filepath, rules_xml=''):
    with open(filepath, 'w') as f:
      f.write(dedent(
        """<?xml version="1.0"?>
           <!DOCTYPE module PUBLIC
             "-//Puppy Crawl//DTD Check Configuration 1.3//EN"
             "http://www.puppycrawl.com/dtds/configuration_1_3.dtd">
           <module name="Checker">
             {rules_xml}
           </module>""".format(rules_xml=rules_xml)))

  @ensure_cached(expected_num_artifacts=2)
  def test_config_invalidates_targets(self, cache_args):
    with self.temporary_workdir() as workdir:
      with temporary_dir(root_dir=get_buildroot()) as tmp:
        configs = [
          dedent("""
              <module name="TreeWalker">
                <property name="tabWidth" value="2"/>
              </module>"""),
          dedent("""
              <module name="TreeWalker">
                <module name="LineLength">
                  <property name="max" value="100"/>
                </module>
              </module>""")
        ]

        for config in configs:
          # Ensure that even though the config files have the same name, their
          # contents will invalidate the targets.
          config_file = os.path.join(tmp, 'config.xml')
          self._create_config_file(config_file, config)
          args = [
            'clean-all',
            'lint',
            cache_args,
            'examples/src/java/org/pantsbuild/example/hello/simple',
            '--lint-checkstyle-configuration={}'.format(config_file)
          ]
          pants_run = self.run_pants_with_workdir(args, workdir)
          self.assert_success(pants_run)

  @ensure_cached(expected_num_artifacts=2)
  def test_config_name_invalidates_targets(self, cache_args):
    with self.temporary_workdir() as workdir:
      with temporary_dir(root_dir=get_buildroot()) as tmp:
        config_names = ['one.xml', 'two.xml']
        config = dedent("""
          <module name="TreeWalker">
            <property name="tabWidth" value="2"/>
          </module>""")

        for config_name in config_names:
          # Ensure that even though the config files have the same name, their contents will
          # invalidate the targets.
          config_file = os.path.join(tmp, config_name)
          self._create_config_file(config_file, config)
          args = [
            'lint',
            cache_args,
            'examples/src/java/org/pantsbuild/example/hello/simple',
            '--lint-checkstyle-configuration={}'.format(config_file)
          ]
          pants_run = self.run_pants_with_workdir(args, workdir)
          self.assert_success(pants_run)

  @contextmanager
  def _temporary_buildroot(self, files_to_copy, current_root=None):
    if current_root is None:
      current_root = get_buildroot()
    files_to_copy = set(files_to_copy)
    files_to_copy.update(f for f in os.listdir(current_root)
                         if f.endswith('.ini') or f.startswith('BUILD'))
    files_to_copy.update((
      'pants',
      '3rdparty',
      'build-support',
      'contrib',
      'pants-plugins',
      'src',
    ))
    with temporary_dir() as temp_root:
      temp_root = os.path.normpath(temp_root)
      for path in files_to_copy:
        src = os.path.join(current_root, path)
        dst = os.path.join(temp_root, path)
        if os.path.isdir(path):
          shutil.copytree(src, dst)
        else:
          shutil.copyfile(src, dst)
      current = os.getcwd()
      try:
        os.chdir(temp_root)
        temp_root = os.getcwd()
        yield temp_root
      finally:
        os.chdir(current)

  def _temporary_buildroots(self, files_to_copy=None, current_root=None, iterations=2):
    while iterations:
      with self._temporary_buildroot(files_to_copy, current_root) as root:
        yield root
      iterations -= 1

  @ensure_cached(expected_num_artifacts=1)
  def test_config_buildroot_does_not_invalidate_targets(self, cache_args):
    previous_names = set()
    for buildroot in self._temporary_buildroots(['examples']):
      with self.temporary_workdir() as workdir:
        tmp = os.path.join(buildroot, 'tmp')
        os.mkdir(tmp)
        config = dedent("""
          <module name="TreeWalker">
            <property name="tabWidth" value="2"/>
          </module>""")

        # Ensure that even though the config files have the same name, their
        # contents will invalidate the targets.
        config_file = os.path.join(tmp, 'one.xml')
        self.assertNotIn(config_file, previous_names)
        previous_names.add(config_file)
        self._create_config_file(config_file, config)
        args = [
          'lint',
          cache_args,
          'examples/src/java/org/pantsbuild/example/hello/simple',
          '--lint-checkstyle-configuration={}'.format(config_file),
        ]
        pants_run = self.run_pants_with_workdir(args, workdir)
        self.assert_success(pants_run)

  @ensure_cached(expected_num_artifacts=1)
  def test_properties_file_names_does_not_invalidates_targets(self, cache_args):
    with self.temporary_workdir() as workdir:
      with temporary_dir(root_dir=get_buildroot()) as tmp:
        suppression_names = ['one-supress.xml', 'two-supress.xml']
        suppression_data = dedent("""
          <?xml version="1.0"?>
          <!DOCTYPE suppressions PUBLIC
              "-//Puppy Crawl//DTD Suppressions 1.1//EN"
              "http://www.puppycrawl.com/dtds/suppressions_1_1.dtd">

          <suppressions>
            <suppress files=".*/bad-files/.*\.java" checks=".*"/>
          </suppressions>
          """).strip()

        for suppression_name in suppression_names:
          suppression_file = os.path.join(tmp, suppression_name)
          self._create_config_file(suppression_file, suppression_data)
          properties = {
            'checkstyle.suppression.files': suppression_file,
          }
          args = [
            'lint',
            cache_args,
            'examples/src/java/org/pantsbuild/example/hello/simple',
            "--lint-checkstyle-properties={}".format(json.dumps(properties)),
          ]
          pants_run = self.run_pants_with_workdir(args, workdir)
          self.assert_success(pants_run)

  @ensure_cached(expected_num_artifacts=2)
  def test_properties_file_contents_invalidates_targets(self, cache_args):
    with self.temporary_workdir() as workdir:
      with temporary_dir(root_dir=get_buildroot()) as tmp:
        suppression_files = [
          dedent("""
            <?xml version="1.0"?>
            <!DOCTYPE suppressions PUBLIC
                "-//Puppy Crawl//DTD Suppressions 1.1//EN"
                "http://www.puppycrawl.com/dtds/suppressions_1_1.dtd">

            <suppressions>
              <suppress files=".*/bad-files/.*\.java" checks=".*"/>
            </suppressions>
          """).strip(),
          dedent("""
            <?xml version="1.0"?>
            <!DOCTYPE suppressions PUBLIC
                "-//Puppy Crawl//DTD Suppressions 1.1//EN"
                "http://www.puppycrawl.com/dtds/suppressions_1_1.dtd">

            <suppressions>
              <suppress files=".*/bad-files/.*\.java" checks=".*"/>
              <suppress files=".*/really-bad-files/.*\.java" checks=".*"/>
            </suppressions>
          """).strip(),
        ]

        for suppressions in suppression_files:
          suppression_file = os.path.join(tmp, 'suppressions.xml')
          self._create_config_file(suppression_file, suppressions)
          properties = {
            'checkstyle.suppression.files': suppression_file,
          }
          args = [
            'lint',
            cache_args,
            'examples/src/java/org/pantsbuild/example/hello/simple',
            "--lint-checkstyle-properties={}".format(json.dumps(properties)),
          ]
          pants_run = self.run_pants_with_workdir(args, workdir)
          self.assert_success(pants_run)

  @ensure_cached(expected_num_artifacts=2)
  def test_properties_nonfile_values_invalidates_targets(self, cache_args):
    with self.temporary_workdir() as workdir:
      with temporary_dir(root_dir=get_buildroot()):
        values = ['this-is-not-a-file', '37']

        for value in values:
          properties = {
            'my.value': value,
          }
          args = [
            'lint',
            cache_args,
            'examples/src/java/org/pantsbuild/example/hello/simple',
            "--lint-checkstyle-properties={}".format(json.dumps(properties)),
          ]
          pants_run = self.run_pants_with_workdir(args, workdir)
          self.assert_success(pants_run)

  @ensure_cached(expected_num_artifacts=2)
  def test_jvm_tool_changes_invalidate_targets(self, cache_args):
    with self.temporary_workdir() as workdir:
      # Ensure that only the second use of the default checkstyle will not invalidate anything.
      for checkstyle_jar in (None, 'testprojects/3rdparty/checkstyle', None):
        args = [
            'lint.checkstyle',
            cache_args,
            '--checkstyle={}'.format(checkstyle_jar) if checkstyle_jar else '',
            'examples/src/java/org/pantsbuild/example/hello/simple'
          ]
        pants_run = self.run_pants_with_workdir(args, workdir)
        print(pants_run.stdout_data)
        self.assert_success(pants_run)
