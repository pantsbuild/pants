# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import pkgutil
import shutil
import tempfile
from xml.dom import minidom

from pants.backend.jvm.targets.java_tests import JavaTests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.project_info.tasks.ide_gen import IdeGen, Project
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.generator import Generator, TemplateData
from pants.base.source_root import SourceRoot
from pants.scm.git import Git
from pants.util.dirutil import safe_mkdir, safe_walk


_TEMPLATE_BASEDIR = 'templates/idea'


_VERSIONS = {
  '9': '12',  # 9 and 12 are ipr/iml compatible
  '10': '12',  # 10 and 12 are ipr/iml compatible
  '11': '12',  # 11 and 12 are ipr/iml compatible
  '12': '12'
}


_SCALA_VERSION_DEFAULT = '2.9'
_SCALA_VERSIONS = {
  '2.8': 'Scala 2.8',
  _SCALA_VERSION_DEFAULT: 'Scala 2.9',
  '2.10': 'Scala 2.10',
  '2.10-virt': 'Scala 2.10 virtualized'
}


class IdeaGen(IdeGen):

  @classmethod
  def register_options(cls, register):
    super(IdeaGen, cls).register_options(register)
    register('--version', choices=sorted(list(_VERSIONS.keys())), default='11',
             help='The IntelliJ IDEA version the project config should be generated for.')
    register('--merge', action='store_true', default=True,
             help='Merge any manual customizations in existing '
                  'Intellij IDEA configuration. If False, manual customizations '
                  'will be over-written.')
    register('--open', action='store_true', default=True,
             help='Attempts to open the generated project in IDEA.')
    register('--bash', action='store_true',
             help='Adds a bash facet to the generated project configuration.')
    register('--scala-language-level',
             choices=_SCALA_VERSIONS.keys(), default=_SCALA_VERSION_DEFAULT,
             help='Set the scala language level used for IDEA linting.')
    register('--scala-maximum-heap-size-mb', type=int, default=512,
             help='Sets the maximum heap size (in megabytes) for scalac.')
    register('--fsc', action='store_true', default=False,
             help='If the project contains any scala targets this specifies the '
                  'fsc compiler should be enabled.')
    register('--java-encoding', default='UTF-8',
             help='Sets the file encoding for java files in this project.')
    register('--java-maximum-heap-size-mb', type=int, default=512,
             help='Sets the maximum heap size (in megabytes) for javac.')
    register('--exclude-maven-target', action='store_true', default=False,
             help="Exclude 'target' directories for directories containing "
                  "pom.xml files.  These directories contain generated code and"
                  "copies of files staged for deployment.")
    register('--exclude_folders', action='append',
             default=[
               '.pants.d/compile',
               '.pants.d/ivy',
               '.pants.d/python',
               '.pants.d/resources',
               ],
             help='Adds folders to be excluded from the project configuration.')
    register('--annotation-processing-enabled', action='store_true',
             help='Tell IntelliJ IDEA to run annotation processors.')
    register('--annotation-generated-sources-dir', default='generated', advanced=True,
             help='Directory relative to --project-dir to write annotation processor sources.')
    register('--annotation-generated-test-sources-dir', default='generated_tests', advanced=True,
             help='Directory relative to --project-dir to write annotation processor sources.')
    register('--annotation-processor', action='append', advanced=True,
             help='Add a Class name of a specific annotation processor to run.')

  def __init__(self, *args, **kwargs):
    super(IdeaGen, self).__init__(*args, **kwargs)

    self.intellij_output_dir = os.path.join(self.gen_project_workdir, 'out')
    self.nomerge = not self.get_options().merge
    self.open = self.get_options().open
    self.bash = self.get_options().bash

    self.scala_language_level = _SCALA_VERSIONS.get(
      self.get_options().scala_language_level, None)
    self.scala_maximum_heap_size = self.get_options().scala_maximum_heap_size_mb

    self.fsc = self.get_options().fsc

    self.java_encoding = self.get_options().java_encoding
    self.java_maximum_heap_size = self.get_options().java_maximum_heap_size_mb

    idea_version = _VERSIONS[self.get_options().version]
    self.project_template = os.path.join(_TEMPLATE_BASEDIR,
                                         'project-{}.mustache'.format(idea_version))
    self.module_template = os.path.join(_TEMPLATE_BASEDIR,
                                        'module-{}.mustache'.format(idea_version))

    self.project_filename = os.path.join(self.cwd,
                                         '{}.ipr'.format(self.project_name))
    self.module_filename = os.path.join(self.gen_project_workdir,
                                        '{}.iml'.format(self.project_name))

  @staticmethod
  def _maven_targets_excludes(repo_root):
    excludes = []
    for (dirpath, dirnames, filenames) in safe_walk(repo_root):
      if "pom.xml" in filenames:
        excludes.append(os.path.join(os.path.relpath(dirpath, start=repo_root), "target"))
    return excludes

  @staticmethod
  def _sibling_is_test(source_set):
    """Determine if a SourceSet represents a test path.

    Non test targets that otherwise live in test target roots (say a java_library), must
    be marked as test for IDEA to correctly link the targets with the test code that uses
    them. Therefore we check to see if the source root registered to the path or any of its sibling
    source roots are defined with a test type.

    :param source_set: SourceSet to analyze
    :returns: True if the SourceSet represents a path containing tests
    """

    def has_test_type(types):
      for target_type in types:
        # TODO(Eric Ayers) Find a way for a target to identify itself instead of a hard coded list
        if target_type in (JavaTests, PythonTests):
          return True
      return False

    if source_set.path:
      path = os.path.join(source_set.source_base, source_set.path)
    else:
      path = source_set.source_base
    sibling_paths = SourceRoot.find_siblings_by_path(path)
    for sibling_path in sibling_paths:
      if has_test_type(SourceRoot.types(sibling_path)):
        return True
    return False

  @property
  def annotation_processing_template(self):
    return TemplateData(
      enabled=self.get_options().annotation_processing_enabled,
      rel_source_output_dir=os.path.join('..','..','..',
                                         self.get_options().annotation_generated_sources_dir),
      source_output_dir=
      os.path.join(self.gen_project_workdir,
                   self.get_options().annotation_generated_sources_dir),
      rel_test_source_output_dir=os.path.join('..','..','..',
                                              self.get_options().annotation_generated_test_sources_dir),
      test_source_output_dir=
      os.path.join(self.gen_project_workdir,
                   self.get_options().annotation_generated_test_sources_dir),
      processors=[{'class_name' : processor}
                  for processor in self.get_options().annotation_processor],
    )

  def generate_project(self, project):
    def create_content_root(source_set):
      root_relative_path = os.path.join(source_set.source_base, source_set.path) \
                           if source_set.path else source_set.source_base

      if self.get_options().infer_test_from_siblings:
        is_test = IdeaGen._sibling_is_test(source_set)
      else:
        is_test = source_set.is_test

      if source_set.resources_only:
        if source_set.is_test:
          content_type = 'java-test-resource'
        else:
          content_type = 'java-resource'
      else:
        content_type = ''

      sources = TemplateData(
        path=root_relative_path,
        package_prefix=source_set.path.replace('/', '.') if source_set.path else None,
        is_test=is_test,
        content_type=content_type
      )

      return TemplateData(
        path=root_relative_path,
        sources=[sources],
        exclude_paths=[os.path.join(source_set.source_base, x) for x in source_set.excludes],
      )

    content_roots = [create_content_root(source_set) for source_set in project.sources]
    if project.has_python:
      content_roots.extend(create_content_root(source_set) for source_set in project.py_sources)

    scala = None
    if project.has_scala:
      scala = TemplateData(
        language_level=self.scala_language_level,
        maximum_heap_size=self.scala_maximum_heap_size,
        fsc=self.fsc,
        compiler_classpath=project.scala_compiler_classpath
      )

    exclude_folders = []
    if self.get_options().exclude_maven_target:
      exclude_folders += IdeaGen._maven_targets_excludes(get_buildroot())

    exclude_folders += self.get_options().exclude_folders

    java_language_level = None
    for target in project.targets:
      if isinstance(target, JvmTarget):
        if java_language_level is None or java_language_level < target.platform.source_level:
          java_language_level = target.platform.source_level
    if java_language_level is not None:
      java_language_level = 'JDK_{0}_{1}'.format(*java_language_level.components[:2])

    configured_module = TemplateData(
      root_dir=get_buildroot(),
      path=self.module_filename,
      content_roots=content_roots,
      bash=self.bash,
      python=project.has_python,
      scala=scala,
      internal_jars=[cp_entry.jar for cp_entry in project.internal_jars],
      internal_source_jars=[cp_entry.source_jar for cp_entry in project.internal_jars
                            if cp_entry.source_jar],
      external_jars=[cp_entry.jar for cp_entry in project.external_jars],
      external_javadoc_jars=[cp_entry.javadoc_jar for cp_entry in project.external_jars
                             if cp_entry.javadoc_jar],
      external_source_jars=[cp_entry.source_jar for cp_entry in project.external_jars
                            if cp_entry.source_jar],
      annotation_processing=self.annotation_processing_template,
      extra_components=[],
      exclude_folders=exclude_folders,
      java_language_level=java_language_level,
    )

    outdir = os.path.abspath(self.intellij_output_dir)
    if not os.path.exists(outdir):
      os.makedirs(outdir)

    configured_project = TemplateData(
      root_dir=get_buildroot(),
      outdir=outdir,
      git_root=Git.detect_worktree(),
      modules=[configured_module],
      java=TemplateData(
        encoding=self.java_encoding,
        maximum_heap_size=self.java_maximum_heap_size,
        jdk=self.java_jdk,
        language_level='JDK_1_{}'.format(self.java_language_level)
      ),
      resource_extensions=list(project.resource_extensions),
      scala=scala,
      checkstyle_classpath=';'.join(project.checkstyle_classpath),
      debug_port=project.debug_port,
      annotation_processing=self.annotation_processing_template,
      extra_components=[],
    )

    existing_project_components = None
    existing_module_components = None
    if not self.nomerge:
      # Grab the existing components, which may include customized ones.
      existing_project_components = self._parse_xml_component_elements(self.project_filename)
      existing_module_components = self._parse_xml_component_elements(self.module_filename)

    # Generate (without merging in any extra components).
    safe_mkdir(os.path.abspath(self.intellij_output_dir))

    ipr = self._generate_to_tempfile(
        Generator(pkgutil.get_data(__name__, self.project_template), project=configured_project))
    iml = self._generate_to_tempfile(
        Generator(pkgutil.get_data(__name__, self.module_template), module=configured_module))

    if not self.nomerge:
      # Get the names of the components we generated, and then delete the
      # generated files.  Clunky, but performance is not an issue, and this
      # is an easy way to get those component names from the templates.
      extra_project_components = self._get_components_to_merge(existing_project_components, ipr)
      extra_module_components = self._get_components_to_merge(existing_module_components, iml)
      os.remove(ipr)
      os.remove(iml)

      # Generate again, with the extra components.
      ipr = self._generate_to_tempfile(Generator(pkgutil.get_data(__name__, self.project_template),
          project=configured_project.extend(extra_components=extra_project_components)))
      iml = self._generate_to_tempfile(Generator(pkgutil.get_data(__name__, self.module_template),
          module=configured_module.extend(extra_components=extra_module_components)))

    self.context.log.info('Generated IntelliJ project in {directory}'
                           .format(directory=self.gen_project_workdir))

    shutil.move(ipr, self.project_filename)
    shutil.move(iml, self.module_filename)
    return self.project_filename if self.open else None

  def _generate_to_tempfile(self, generator):
    """Applies the specified generator to a temp file and returns the path to that file.
    We generate into a temp file so that we don't lose any manual customizations on error."""
    (output_fd, output_path) = tempfile.mkstemp()
    with os.fdopen(output_fd, 'w') as output:
      generator.write(output)
    return output_path

  def _get_resource_extensions(self, project):
    resource_extensions = set()
    resource_extensions.update(project.resource_extensions)

    # TODO(John Sirois): make test resources 1st class in ant build and punch this through to pants
    # model
    for _, _, files in safe_walk(os.path.join(get_buildroot(), 'tests', 'resources')):
      resource_extensions.update(Project.extract_resource_extensions(files))

    return resource_extensions

  def _parse_xml_component_elements(self, path):
    """Returns a list of pairs (component_name, xml_fragment) where xml_fragment is the xml text of
    that <component> in the specified xml file."""
    if not os.path.exists(path):
      return []  # No existing components.
    dom = minidom.parse(path)
    # .ipr and .iml files both consist of <component> elements directly under a root element.
    return [(x.getAttribute('name'), x.toxml()) for x in dom.getElementsByTagName('component')]

  def _get_components_to_merge(self, mergable_components, path):
    """Returns a list of the <component> fragments in mergable_components that are not
    superceded by a <component> in the specified xml file.
    mergable_components is a list of (name, xml_fragment) pairs."""

    # As a convenience, we use _parse_xml_component_elements to get the
    # superceding component names, ignoring the generated xml fragments.
    # This is fine, since performance is not an issue.
    generated_component_names = set(
      [name for (name, _) in self._parse_xml_component_elements(path)])
    return [x[1] for x in mergable_components if x[0] not in generated_component_names]
