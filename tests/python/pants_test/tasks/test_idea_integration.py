# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import xml.dom.minidom as minidom

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IdeaIntegrationTest(PantsRunIntegrationTest):

  def _idea_test(self, specs, project_dir=os.path.join('.pants.d', 'idea', 'idea', 'IdeaGen'),
      project_name=None, check_func=None, config=None):
    """Helper method that tests idea generation on the input spec list.
    :param project_dir: directory passed to --idea-project-dir
    :param project_name: name passed to --idea-project-name
    :param check_func: method to call back with the directory where project files are written.
    :param dict config: pants.ini configuration parameters
    """

    project_dir = os.path.join(get_buildroot(), project_dir)
    if not os.path.exists(project_dir):
      os.makedirs(project_dir)

    with temporary_dir(root_dir=project_dir) as project_dir_path:

      extra_flags = ['--idea-project-dir={dir}'.format(dir=project_dir_path)]

      if project_name is None:
        project_name = "project" # to match Pants' built-in default w/o --idea-project-name
      else:
        extra_flags += ['--idea-project-name={name}'.format(name=project_name)]

      all_flags = ['goal', 'idea',] + specs + \
                  ['--no-pantsrc', '--no-idea-open', '--print-exception-stacktrace' ] + extra_flags
      pants_run = self.run_pants(all_flags, config=config)
      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal idea expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))

      expected_files = ('{project_name}.iml'.format(project_name=project_name),
                        '{project_name}.ipr'.format(project_name=project_name))

      workdir = os.path.join(project_dir_path, project_name)
      self.assertTrue(os.path.exists(workdir),
                      'exec ./pants {all_flags}. Failed to find project_dir at {dir}.'
                      .format(all_flags=" ".join(all_flags), dir=workdir))
      self.assertTrue(all(os.path.exists(os.path.join(workdir, name))
                          for name in expected_files),
                      msg="Failed to exec ./pants {all_flags}".format(all_flags=all_flags))
      if check_func:
        check_func(workdir)

  def _get_new_module_root_manager(self, dom):
    module = dom.getElementsByTagName('module')[0]
    components = module.getElementsByTagName('component')
    for component in components:
      if component.getAttribute('name') == 'NewModuleRootManager':
        return module.getElementsByTagName('content')[0]
    return None

  def _get_sourceFolders(self, dom):
    """Navigate the dom to return the list of all <sourceFolder> entries in the project file"""
    return self._get_new_module_root_manager(dom).getElementsByTagName('sourceFolder')

  def _get_excludeFolders(self, dom):
    """Navigate the dom to return the list of all <excludeFolder> entries in the project file"""
    return self._get_new_module_root_manager(dom).getElementsByTagName('excludeFolder')

  # Testing IDEA integration on lots of different targets which require different functionalities to
  # make sure that everything that needs to happen for idea gen does happen.
  # TODO(Garrett Malmquist): Actually validate the contents of the project files, rather than just
  # checking if they exist.
  def test_idea_on_alternate_project_dir(self):
    alt_dir = os.path.join('.pants.d', 'tmp', 'some', 'random', 'directory', 'for', 'idea', 'stuff')
    self._idea_test(['examples/src/java/com/pants/examples/hello::'], project_dir=alt_dir)

  def test_idea_alternate_name(self):
    alt_name = "alt-name"
    self._idea_test(['examples/src/java/com/pants/examples/hello::'], project_name=alt_name)

  def test_idea_on_protobuf(self):
    self._idea_test(['examples/src/java/com/pants/examples/protobuf::'])

  def test_idea_on_jaxb(self): # Make sure it works without ::, pulling deps as necessary.
    self._idea_test(['examples/src/java/com/pants/examples/jaxb/main'])

  def test_idea_on_unicode(self):
    self._idea_test(['testprojects/src/java/com/pants/testproject/unicode::'])

  def test_idea_on_hello(self):
    def do_check(path):
      """Check to see that the project contains the expected source folders."""
      found_source_content = False
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      expected_paths = ["file://" + os.path.join(get_buildroot(), path) for path in [
        'examples/src/java/com/pants/example/hello',
        'examples/src/java/com/pants/examples/hello/greet',
        'examples/src/java/com/pants/examples/hello/main',
        'examples/src/resources/com/pants/example/hello',
      ]]
      remaining = set(expected_paths)
      for sourceFolder in self._get_sourceFolders(dom):
        found_source_content = True
        self.assertEquals("False", sourceFolder.getAttribute('isTestSource'))
        url = sourceFolder.getAttribute('url')
        self.assertIn(url, remaining,
                       msg="Couldn't find url={url} in {expected}".format(url=url,
                                                                          expected=expected_paths))
        remaining.remove(url)
      self.assertTrue(found_source_content)

    self._idea_test(['examples/src/java/com/pants/examples/hello::'], check_func=do_check)

  def test_idea_on_annotations(self):
    self._idea_test(['examples/src/java/com/pants/examples/annotation::'])

  def test_idea_on_all_examples(self):
    self._idea_test(['examples/src/java/com/pants/examples::'])

  def test_idea_on_java_sources(self):
    self._idea_test(['testprojects/src/scala/com/pants/testproject/javasources::'])

  def test_idea_on_thriftdeptest(self):
    self._idea_test(['testprojects/src/java/com/pants/testproject/thriftdeptest::'])

  def test_idea_on_scaladepsonboth(self):
    self._idea_test(['testprojects/src/scala/com/pants/testproject/scaladepsonboth::'])

  def test_idea_on_maven_layout(self):
    def do_check(path):
      """
          The contents of the .iml file should have sourceFolder entries that all look like:
          <sourceFolder url=".../src/main/java"  isTestSource="False"/>
          <sourceFolder url=".../src/main/resources"  isTestSource="False"/>
          <sourceFolder url=".../src/test/java"  isTestSource="True"/>
          <sourceFolder url=".../src/test/resources"  isTestSource="True"/>
          ...
      """
      found_source_content = False
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      for sourceFolder in  self._get_sourceFolders(dom):
        found_source_content = True
        url = sourceFolder.getAttribute('url')
        is_test_source = sourceFolder.getAttribute('isTestSource')
        if url.endswith("src/main/java") or url.endswith("src/main/resources"):
          self.assertEquals("False", is_test_source,
                           msg="wrong test flag: url={url} isTestSource={is_test_source}"
                           .format(url=url, is_test_source=is_test_source))
        elif url.endswith("src/test/java") or url.endswith("src/test/resources"):
          self.assertEquals("True", is_test_source,
                          msg="wrong test flag: url={url} isTestSource={is_test_source}"
                          .format(url=url, is_test_source=is_test_source))
        else:
          self.fail("Unexpected sourceContent tag: url={url} isTestSource={is_test_source}"
          .format(url=url, is_test_source=is_test_source))
      self.assertTrue(found_source_content)

    self._idea_test(['testprojects/maven_layout/resource_collision::', '--idea-use-source-root',
                     '--idea-infer-test-from-siblings',],
                    check_func=do_check)

  def test_idea_exclude_maven_targets(self):
    def do_check(path):
      """Expect to see at least these two excludeFolder entries:

       <excludeFolder url="file://.../testprojects/maven_layout/protolib-test/target" />
       <excludeFolder url="file://.../testprojects/maven_layout/maven_and_pants/target" />

       And this source entry:
       <sourceFolder url="file://.../testprojects/maven_layout/maven_and_pants/src/main/java"
         isTestSource="False" />
      """
      found_source_content = False
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      for sourceFolder in  self._get_sourceFolders(dom):
        found_source_content = True
        url = sourceFolder.getAttribute('url')
        self.assertTrue(url.endswith("testprojects/maven_layout/maven_and_pants/src/main/java"),
                        msg="Unexpected url={url}".format(url=url))
        self.assertEquals("False", sourceFolder.getAttribute('isTestSource'))
      self.assertTrue(found_source_content)

      expected = ["testprojects/maven_layout/protolib-test/target",
                  "testprojects/maven_layout/maven_and_pants/target"]
      found_exclude_folders = [excludeFolder.getAttribute('url')
                               for excludeFolder in self._get_excludeFolders(dom)]
      for suffix in expected:
        found = False
        for url in found_exclude_folders:
          if url.endswith(suffix):
            found = True
            break
        self.assertTrue(found, msg="suffix {suffix} not found in {foundExcludeFolders}"
                        .format(suffix=suffix, foundExcludeFolders=found_exclude_folders))
    # Test together with --idea-use-source-root because that makes sense in a Maven environment
    self._idea_test(['testprojects/maven_layout/maven_and_pants::', '--idea-exclude-maven-target',
                     '--idea-use-source-root',],
                    check_func=do_check)

  def test_idea_excludeFolders(self):
    def assertExpectedInExcludeFolders(path, expected):
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      found_exclude_folders = [excludeFolder.getAttribute('url')
                               for excludeFolder in self._get_excludeFolders(dom)]
      for suffix in expected:
        found = False
      for url in found_exclude_folders:
        if url.endswith(suffix):
          found = True
          break
      self.assertTrue(found, msg="suffix {suffix} not found in {foundExcludeFolders}"
                      .format(suffix=suffix, foundExcludeFolders=found_exclude_folders))
    def do_check_default(path):
      assertExpectedInExcludeFolders(path, ["/compile", "/ivy",  "/python", "/resources"])
    def do_check_override(path):
      assertExpectedInExcludeFolders(path, ["exclude-folder-sentinel"])

    self._idea_test(['examples/src/java/com/pants/examples/hello::'], check_func=do_check_default)
    self._idea_test(['examples/src/java/com/pants/examples/hello::'], check_func=do_check_override,
                    config= {
                      'idea': {'exclude_folders': ['exclude-folder-sentinel']}
                    })
