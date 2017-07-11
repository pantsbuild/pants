# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import xml.dom.minidom as minidom

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants_test.backend.project_info.tasks.resolve_jars_test_mixin import ResolveJarsTestMixin
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class IdeaIntegrationTest(ResolveJarsTestMixin, PantsRunIntegrationTest):

  RESOURCE = 'java-resource'
  TEST_RESOURCE = 'java-test-resource'

  def _idea_test(self, specs, project_dir=os.path.join('.pants.d', 'idea', 'idea', 'IdeaGen'),
                 project_name=None, check_func=None, config=None, load_extra_confs=True,
                 extra_args=None):
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
      extra_flags.extend(extra_args or ())

      if project_name is None:
        project_name = "project"  # to match Pants' built-in default w/o --idea-project-name
      else:
        extra_flags += ['--idea-project-name={name}'.format(name=project_name)]

      if not load_extra_confs:
        extra_flags += ['--no-idea-source-jars', '--no-idea-javadoc-jars']

      all_flags = ['idea', '--no-open'] + specs + extra_flags
      pants_run = self.run_pants(all_flags, config=config)
      self.assert_success(pants_run)

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

  def evaluate_subtask(self, targets, workdir, load_extra_confs, extra_args, expected_jars):
    def check(path):
      for jar in expected_jars:
        parts = jar.split(':')
        jar_name = '{}.jar'.format('-'.join(parts[1:]))
        jar_path = os.path.join(get_buildroot(), path, 'external-libs', jar_name)
        self.assertTrue(os.path.exists(jar_path), 'Expected {} to exist.'.format(jar_path))

    self._idea_test(targets, load_extra_confs=load_extra_confs, extra_args=extra_args,
                    check_func=check)

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

  def _get_external_libraries(self, dom, type='CLASSES'):
    """Return 'root' elements under <CLASSES>, <JAVADOC>, or <SOURCES> for <library name='external'>"""
    module = dom.getElementsByTagName('module')[0]
    components = module.getElementsByTagName('component')
    for component in components:
      if component.getAttribute('name') == 'NewModuleRootManager':
        for orderEntry in component.getElementsByTagName('orderEntry'):
          for library in orderEntry.getElementsByTagName('library'):
            if library.getAttribute('name') == 'external':
              for library_type in library.getElementsByTagName(type):
                return library_type.getElementsByTagName('root')
    return None

  def _get_compiler_configuration(self, dom):
    project = dom.getElementsByTagName('project')[0]
    for component in project.getElementsByTagName('component'):
      if component.getAttribute('name') == 'CompilerConfiguration':
        return component
    return None

  # Testing IDEA integration on lots of different targets which require different functionalities to
  # make sure that everything that needs to happen for idea gen does happen.
  # TODO(Garrett Malmquist): Actually validate the contents of the project files, rather than just
  # checking if they exist.
  def test_idea_on_alternate_project_dir(self):
    alt_dir = os.path.join('.pants.d', 'tmp', 'some', 'random', 'directory', 'for', 'idea', 'stuff')
    self._idea_test(['examples/src/java/org/pantsbuild/example/hello::'], project_dir=alt_dir)

  def test_idea_alternate_name(self):
    alt_name = "alt-name"
    self._idea_test(['examples/src/java/org/pantsbuild/example/hello::'], project_name=alt_name)

  def test_idea_on_protobuf(self):
    self._idea_test(['examples/src/java/org/pantsbuild/example/protobuf::'])

  def test_idea_on_jaxb(self):  # Make sure it works without ::, pulling deps as necessary.
    self._idea_test(['examples/src/java/org/pantsbuild/example/jaxb/main'])

  def test_idea_on_unicode(self):
    self._idea_test(['testprojects/src/java/org/pantsbuild/testproject/unicode::'])

  def test_idea_on_hello(self):
    def do_check(path):
      """Check to see that the project contains the expected source folders."""
      found_source_content = False
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      expected_paths = ["file://" + os.path.join(get_buildroot(), _path) for _path in [
        'examples/src/java/org/pantsbuild/example/hello',
        'examples/src/java/org/pantsbuild/example/hello/greet',
        'examples/src/java/org/pantsbuild/example/hello/main',
        'examples/src/java/org/pantsbuild/example/hello/simple',
        'examples/src/resources/org/pantsbuild/example/hello',
      ]]
      expected_java_resource = ["file://" + os.path.join(get_buildroot(), _path) for _path in [
        'examples/src/resources/org/pantsbuild/example/hello',
      ]]
      remaining = set(expected_paths)
      for sourceFolder in self._get_sourceFolders(dom):
        found_source_content = True
        self.assertEquals("False", sourceFolder.getAttribute('isTestSource'))
        url = sourceFolder.getAttribute('url')
        # Check is resource attribute is set correctly
        if url in expected_java_resource:
          self.assertEquals(sourceFolder.getAttribute('type'), IdeaIntegrationTest.RESOURCE,
                            msg="Type {c_type} does not match expected type {a_type} "
                                "for {url}".format(c_type=IdeaIntegrationTest.RESOURCE, url=url,
                                                   a_type=sourceFolder.getAttribute('type')))
        self.assertIn(url, remaining,
                       msg="Couldn't find url={url} in {expected}".format(url=url,
                                                                          expected=expected_paths))
        remaining.remove(url)
      self.assertTrue(found_source_content)

    self._idea_test(['examples/src/java/org/pantsbuild/example/hello::'], check_func=do_check)

  def test_idea_on_annotations(self):
    self._idea_test(['examples/src/java/org/pantsbuild/example/annotation::'])

  def test_idea_on_all_examples(self):
    self._idea_test(['examples/src/java/org/pantsbuild/example::'])

  def _check_javadoc_and_sources(self, path, library_name, with_sources=True, with_javadoc=True):
    """
    :param path: path to the idea project directory
    :param library_name: name of the library to check for (e.g. guava)
    """
    def _get_module_library_orderEntry(dom):
      module = dom.getElementsByTagName('module')[0]
      components = module.getElementsByTagName('component')
      for component in components:
        if component.getAttribute('name') == 'NewModuleRootManager':
          for orderEntry in component.getElementsByTagName('orderEntry'):
            if orderEntry.getAttribute('type') == 'module-library':
              for library in orderEntry.getElementsByTagName('library'):
                if library.getAttribute('name') == 'external':
                  return library
      return None

    iml_file = os.path.join(path, 'project.iml')
    self.assertTrue(os.path.exists(iml_file))
    dom = minidom.parse(iml_file)
    libraryElement = _get_module_library_orderEntry(dom)
    sources = libraryElement.getElementsByTagName('SOURCES')[0]
    sources_found = False
    roots = sources.getElementsByTagName('root')
    for root in roots:
      url = root.getAttribute('url')
      if re.match(r'.*\bexternal-libsources\b.*{library_name}\b.*-sources\.jar\b.*$'
                      .format(library_name=library_name), url):
        sources_found = True
        break
    if with_sources:
      self.assertTrue(sources_found)
    else:
      self.assertFalse(sources_found)

    javadoc = libraryElement.getElementsByTagName('JAVADOC')[0]
    javadoc_found = False
    for root in javadoc.getElementsByTagName('root'):
      url = root.getAttribute('url')
      if re.match(r'.*\bexternal-libjavadoc\b.*{library_name}\b.*-javadoc\.jar\b.*$'
                      .format(library_name=library_name), url):
        javadoc_found = True
        break
    if with_javadoc:
      self.assertTrue(javadoc_found)
    else:
      self.assertFalse(javadoc_found)

  # NOTE(Garrett Malmquist): The test below assumes that the annotation example's dependency on
  # guava will never be removed. If it ever is, these tests will need to be changed to check for a
  # different 3rdparty jar library.
  # Testing for:
  # <orderEntry type="module-library">
  #  <library name="external">
  #    ...
  #   <JAVADOC>
  #    <root url="jar://$MODULE_DIR$/external-libjavadoc/guava-16.0-javadoc.jar!/" />
  #   </JAVADOC>
  #   <SOURCES>
  #     <root url="jar://$MODULE_DIR$/external-libsources/guava-16.0-sources.jar!/" />
  #   </SOURCES>
  #  </library>
  # </orderEntry>
  def test_idea_external_javadoc_and_sources(self):
    def do_check(path):
      self._check_javadoc_and_sources(path, 'guava')

    def do_check_no_sources(path):
      self._check_javadoc_and_sources(path, 'guava', with_sources=False)

    def do_check_no_javadoc(path):
      self._check_javadoc_and_sources(path, 'guava', with_javadoc=False)

    self._idea_test(['examples/src/java/org/pantsbuild/example/annotation::'],
                    check_func=do_check)
    self._idea_test(['examples/src/java/org/pantsbuild/example/annotation::', '--idea-no-source-jars'],
                    check_func=do_check_no_sources)
    self._idea_test(['examples/src/java/org/pantsbuild/example/annotation::', '--idea-no-javadoc-jars'],
                    check_func=do_check_no_javadoc)

  def test_idea_on_java_sources(self):
    self._idea_test(['testprojects/src/scala/org/pantsbuild/testproject/javasources::'])

  def test_idea_missing_sources(self):
    """Test what happens if we try to fetch sources from a jar that doesn't have any."""
    self._idea_test(['testprojects/src/java/org/pantsbuild/testproject/missing_sources'])

  def test_idea_on_thriftdeptest(self):
    self._idea_test(['testprojects/src/java/org/pantsbuild/testproject/thriftdeptest::'])

  def test_idea_on_scaladepsonboth(self):
    self._idea_test(['testprojects/src/scala/org/pantsbuild/testproject/scaladepsonboth::'])

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
      for sourceFolder in self._get_sourceFolders(dom):
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

    self._idea_test(['testprojects/maven_layout/resource_collision::', '--idea-use-source-root'],
                    check_func=do_check)

  def _test_idea_language_level(self, targets, expected):
    def do_check(path):
      iml_file = os.path.join(path, 'project.iml')
      dom = minidom.parse(iml_file)
      module = dom.getElementsByTagName('module')[0]
      for component in module.getElementsByTagName('component'):
        if component.getAttribute('name') == 'NewModuleRootManager':
          received = component.getAttribute('LANGUAGE_LEVEL')
          self.assertEquals(expected, received,
                            'Language level was {0} instead of {1}.'.format(received, expected))
          break
    self._idea_test(targets, check_func=do_check)

  def test_idea_language_level_homogenous(self):
    self._test_idea_language_level(
      targets=['testprojects/src/java/org/pantsbuild/testproject/targetlevels/java7'],
      expected='JDK_1_7'
    )

  def test_idea_language_level_heterogenous(self):
    self._test_idea_language_level(
      targets=['testprojects/src/java/org/pantsbuild/testproject/targetlevels/java7',
               'testprojects/src/java/org/pantsbuild/testproject/targetlevels/java8'],
      expected='JDK_1_8'
    )

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
      for sourceFolder in self._get_sourceFolders(dom):
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
                     '--idea-use-source-root'],
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
      assertExpectedInExcludeFolders(path, ["/compile", "/ivy", "/python", "/resources"])

    def do_check_override(path):
      assertExpectedInExcludeFolders(path, ["exclude-folder-sentinel"])

    self._idea_test(['examples/src/java/org/pantsbuild/example/hello::'], check_func=do_check_default)
    self._idea_test(['examples/src/java/org/pantsbuild/example/hello::'], check_func=do_check_override,
                    config={
                      'idea': {'exclude_folders': ['exclude-folder-sentinel']}
                    })

  @ensure_engine
  def test_all_targets(self):
    self._idea_test([
      'src::', 'tests::', 'examples::', 'testprojects::',
      '--gen-protoc-import-from-root',
      # IdeaGen resolves source jars by default, which causes a collision with these targets because
      # they explicitly include jersey.jersey's source jar.
      '--exclude-target-regexp=testprojects/3rdparty/managed:jersey.jersey.sources',
      '--exclude-target-regexp=testprojects/3rdparty/managed:example-dependee',
      # This target fails by design.
      '--exclude-target-regexp=testprojects/src/antlr/python/test:antlr_failure',
      '--jvm-platform-default-platform=java7'
    ])

  def test_ivy_classifiers(self):
    def do_check(path):
      """Check to see that the project contains the expected jar files."""
      def check_jars(jars, expected_jars):
        # Make sure the .jar files are present on disk
        for jar in expected_jars:
          self.assertTrue(os.path.exists(jar), '{} does not exist.'.format(jar))
        to_find = set('jar://{}!/'.format(jar) for jar in expected_jars)
        for external_library in jars:
          to_find.discard(external_library.getAttribute('url'))
        self.assertEqual(set(), to_find)

      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      base = os.path.join(get_buildroot(), path)
      check_jars(self._get_external_libraries(dom, type='CLASSES'),
                 [os.path.join(base, 'external-libs', jar_path)
                  for jar_path in ['avro-1.7.7.jar', 'avro-1.7.7-tests.jar']])
      check_jars(self._get_external_libraries(dom, type='SOURCES'),
                 [os.path.join(base, 'external-libsources', 'avro-1.7.7-sources.jar')])
      check_jars(self._get_external_libraries(dom, type='JAVADOC'),
                 [os.path.join(base, 'external-libjavadoc', 'avro-1.7.7-javadoc.jar')])

    self._idea_test(['testprojects/tests/java/org/pantsbuild/testproject/ivyclassifier::'],
                    check_func=do_check)

  def test_resource_only_content_type(self):
    """Folders containing just resources() targets should be marked as Resources in IntelliJ"""

    def do_check(path):
      """The contents of the .iml file should certain sourceFolder entries:

      <sourceFolder url=".../testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/resources_and_code" isTestSource="false" />
      <sourceFolder url=".../testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/resources_only" type="java-resource" />
      <sourceFolder url=".../testprojects/src/resources/org/pantsbuild/testproject/idearesourcesonly" type="java-resource" />
          ...
      """
      found = set()
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      for sourceFolder in self._get_sourceFolders(dom):
        url = sourceFolder.getAttribute('url')
        is_test_source = sourceFolder.getAttribute('isTestSource')
        type_attr = sourceFolder.getAttribute('type')
        url = re.sub(r'^.*/testprojects/', 'testprojects/', url)
        found.add(url)
        if url == 'testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/code':
          self.assertEquals('', type_attr)
          self.assertEquals('False', is_test_source)
        if url == 'testprojects/tests/java/org/pantsbuild/testproject/idearesourcesonly/code':
          self.assertEquals('', type_attr)
          self.assertEquals('True', is_test_source)
        if url == 'testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/resources_only':
          self.assertEquals('java-resource', type_attr)
          self.assertEquals('False', is_test_source)
        # TODO(Eric Ayers) tests/resources/.../idearesourcesonly : this directory has no
        # junit_tests depending on a target, so it is assumed to be plain resources.
        # Since this is under .../tests, humans know this is supposed to be a test only
        # resource.  Right now we don't have a good way of communicating
        # that to the idea goal other than inferring from the presence of junit_tests in
        # source_root, which may not be a reliable indicator.
        if url == 'testprojects/tests/java/org/pantsbuild/testproject/idearesourcesonly/resources_only':
          self.assertEquals('java-resource', type_attr)
          self.assertEquals('False', is_test_source)
        if url == 'testprojects/src/resources/org/pantsbuild/testproject/idearesourcesonly':
          self.assertEquals('java-resource', type_attr)
          self.assertEquals('False', is_test_source)
        if url == 'testprojects/tests/resources/org/pantsbuild/testproject/idearesourcesonly':
          self.assertEquals('java-test-resource', type_attr)
          self.assertEquals('True', is_test_source)

      self.assertEquals(set([
        'testprojects/src/resources/org/pantsbuild/testproject/idearesourcesonly',
        'testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/code',
        'testprojects/tests/resources/org/pantsbuild/testproject/idearesourcesonly',
        'testprojects/tests/java/org/pantsbuild/testproject/idearesourcesonly/code',
        'testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/resources_only',
        'testprojects/tests/java/org/pantsbuild/testproject/idearesourcesonly/resources_only'
      ]), found)

    self._idea_test([
        'testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly::',
        'testprojects/tests/java/org/pantsbuild/testproject/idearesourcesonly::'
      ], check_func=do_check)

  def test_resource_and_code_content_type(self):
    """Folders containing just resources() targets should be marked as Resources in IntelliJ.

    This test introduces more cases, like code co-mingled with resources targets, and test targets
    that rely on non-test resources folders
    """

    def do_check(path):
      """The contents of the .iml file should certain sourceFolder entries:

      <sourceFolder url=".../testprojects/src/java/org/pantsbuild/testproject/ideacodeandresources/resources_and_code" isTestSource="false" />
      <sourceFolder url=".../testprojects/src/java/org/pantsbuild/testproject/ideacodeandresources/resources_only" type="java-resource" />
      <sourceFolder url=".../testprojects/src/resources/org/pantsbuild/testproject/ideacodeandresources" type="java-resource" />
          ...
      """
      found = set()
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      for sourceFolder in self._get_sourceFolders(dom):
        url = sourceFolder.getAttribute('url')
        is_test_source = sourceFolder.getAttribute('isTestSource')
        type_attr = sourceFolder.getAttribute('type')
        url = re.sub(r'^.*/testprojects/', 'testprojects/', url)
        found.add(url)
        if url == 'testprojects/src/resources/org/pantsbuild/testproject/ideacodeandresources':
          self.assertEquals('java-resource', type_attr)
          self.assertEquals('False', is_test_source)
        if url == 'testprojects/tests/resources/org/pantsbuild/testproject/ideacodeandresources':
          self.assertEquals('java-test-resource', type_attr)
          self.assertEquals('True', is_test_source)
        if url == 'testprojects/src/java/org/pantsbuild/testproject/ideacodeandresources':
          self.assertEquals('', type_attr)
          self.assertEquals('False', is_test_source)
        if url == 'testprojects/tests/java/org/pantsbuild/testproject/ideacodeandresources':
          self.assertEquals('', type_attr)
          self.assertEquals('True', is_test_source)

      self.assertEquals(set([
        'testprojects/src/resources/org/pantsbuild/testproject/ideacodeandresources',
        'testprojects/src/java/org/pantsbuild/testproject/ideacodeandresources',
        'testprojects/tests/resources/org/pantsbuild/testproject/ideacodeandresources',
        'testprojects/tests/java/org/pantsbuild/testproject/ideacodeandresources',
      ]), found)

    self._idea_test([
      'testprojects/src/java/org/pantsbuild/testproject/ideacodeandresources::',
      'testprojects/tests/java/org/pantsbuild/testproject/ideacodeandresources::'
    ], check_func=do_check)

  def test_library_and_test_code(self):
    """Folders containing both junit_tests() and java_library() targets should be Test folders."""

    def do_check(path):
      """The contents of the .iml file should certain sourceFolder entries:

      <sourceFolder url=".../testprojects/tests/java/org/pantsbuild/testproject/ideatestsandlib" isTestSource="true" />
      """
      found = set()
      iml_file = os.path.join(path, 'project.iml')
      self.assertTrue(os.path.exists(iml_file))
      dom = minidom.parse(iml_file)
      for sourceFolder in self._get_sourceFolders(dom):
        url = sourceFolder.getAttribute('url')
        is_test_source = sourceFolder.getAttribute('isTestSource')
        type_attr = sourceFolder.getAttribute('type')
        url = re.sub(r'^.*/testprojects/', 'testprojects/', url)
        found.add(url)
        if url == 'testprojects/tests/java/org/pantsbuild/testproject/ideatestsandlib':
          self.assertEquals('', type_attr)
          self.assertEquals('True', is_test_source)

      self.assertEquals(set([
        'testprojects/tests/java/org/pantsbuild/testproject/ideatestsandlib',
      ]), found)

    self._idea_test([
      'testprojects/tests/java/org/pantsbuild/testproject/ideatestsandlib::'
    ], check_func=do_check)

  def test_annotation_processor(self):
    """Turn on annotation processor support for AutoValue in IntellliJ"""

    def do_check(path):
      iml_file = os.path.join(path, 'project.iml')
      iml_dom = minidom.parse(iml_file)
      found_paths = set()
      for sourceFolder in self._get_sourceFolders(iml_dom):
        url = sourceFolder.getAttribute('url')
        source_path = re.sub(r'^.*/generated', 'generated', url)
        found_paths.add(source_path)
      self.assertIn("generated", found_paths)
      self.assertIn("generated_tests", found_paths)

      ipr_file = os.path.join(path, 'project.ipr')
      ipr_dom = minidom.parse(ipr_file)
      annotation_processing = self._get_compiler_configuration(ipr_dom).getElementsByTagName(
        'annotationProcessing')[0]
      profile = annotation_processing.getElementsByTagName('profile')[0]
      self.assertEquals('True', profile.getAttribute('enabled'))
      self.assertEquals('true', profile.getAttribute('default'))
      self.assertEquals('Default', profile.getAttribute('name'))
      processor_path = profile.getElementsByTagName('processorPath')[0]
      self.assertEquals('true', processor_path.getAttribute('useClasspath'))
      source_output_dir = profile.getElementsByTagName('sourceOutputDir')[0]
      self.assertEquals('../../../generated', source_output_dir.getAttribute('name'))
      source_test_output_dir = profile.getElementsByTagName('sourceTestOutputDir')[0]
      self.assertEquals('../../../generated_tests', source_test_output_dir.getAttribute('name'))
      found_processors = set()
      for processor in profile.getElementsByTagName('processor'):
        found_processors.add(processor.getAttribute('name'))
      self.assertEquals({'com.google.auto.value.processor.AutoAnnotationProcessor',
                         'com.google.auto.value.processor.AutoValueBuilderProcessor',
                         'com.google.auto.value.processor.AutoValueProcessor'},
                        found_processors)

    self._idea_test([
      'examples/src/java/org/pantsbuild/example/autovalue::',
      '--idea-annotation-processing-enabled',
      '--idea-annotation-processor=com.google.auto.value.processor.AutoAnnotationProcessor',
      '--idea-annotation-processor=com.google.auto.value.processor.AutoValueBuilderProcessor',
      '--idea-annotation-processor=com.google.auto.value.processor.AutoValueProcessor',
    ], check_func=do_check)
