# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pkgutil
import shutil
import tempfile
from xml.dom import minidom

from pants.backend.jvm.tasks.ide_gen import IdeGen, Project, SourceSet
from pants.base.build_environment import get_buildroot
from pants.base.config import ConfigOption
from pants.base.generator import Generator, TemplateData
from pants.util.dirutil import safe_mkdir


_TEMPLATE_BASEDIR = 'templates/idea'


_VERSIONS = {
  '9': '12', # 9 and 12 are ipr/iml compatible
  '10': '12', # 10 and 12 are ipr/iml compatible
  '11': '12', # 11 and 12 are ipr/iml compatible
  '12': '12'
}


_SCALA_VERSION_DEFAULT = '2.9'
_SCALA_VERSIONS = {
  '2.8':                  'Scala 2.8',
  _SCALA_VERSION_DEFAULT: 'Scala 2.9',
  '2.10':                 'Scala 2.10',
  '2.10-virt':            'Scala 2.10 virtualized'
}


class IdeaGen(IdeGen):
  _IDEA_JAVA_MAX_HEAP_MB = ConfigOption.create(
    section='idea',
    option='java_maximum_heap_size_mb',
    help='Max heap size for javac in megabytes.',
    valtype=int,
    default=512)

  _IDEA_SCALA_MAX_HEAP_MB = ConfigOption.create(
    section='idea',
    option='scala_maximum_heap_size_mb',
    help='Max heap size for scalac in megabytes.',
    valtype=int,
    default=512)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(IdeaGen, cls).setup_parser(option_group, args, mkflag)

    supported_versions = sorted(list(_VERSIONS.keys()))
    option_group.add_option(mkflag("idea-version"), dest="idea_gen_version",
                            default='11', type="choice", choices=supported_versions,
                            help="[%%default] The IntelliJ IDEA version the project "
                                   "configuration should be generated for; can be one of: " \
                                   "%s" % supported_versions)

    option_group.add_option(mkflag("merge"), mkflag("merge", negate=True), default=True,
                            action="callback", callback=mkflag.set_bool, dest="idea_gen_merge",
                            help="[%default] Merge any manual customizations in existing "
                                   "Intellij IDEA configuration. If False, manual customizations "
                                   "will be over-written.")

    option_group.add_option(mkflag("open"), mkflag("open", negate=True), default=True,
                            action="callback", callback=mkflag.set_bool, dest="idea_gen_open",
                            help="[%default] Attempts top open the generated project in IDEA.")

    option_group.add_option(mkflag("bash"), mkflag("bash", negate=True), default=False,
                            action="callback", callback=mkflag.set_bool, dest="idea_gen_bash",
                            help="Adds a bash facet to the generated project configuration.")

    option_group.add_option(mkflag("scala-language-level"), default=_SCALA_VERSION_DEFAULT,
                            type="choice", choices=_SCALA_VERSIONS.keys(),
                            dest="idea_scala_language_level",
                            help="[%default] Set the scala language level used for IDEA linting.")
    option_group.add_option(mkflag("scala-maximum-heap-size"),
                            dest="idea_gen_scala_maximum_heap_size",
                            help="[%default] Sets the maximum heap size (in megabytes) for scalac.")
    option_group.add_option(mkflag("fsc"), mkflag("fsc", negate=True), default=False,
                            action="callback", callback=mkflag.set_bool, dest="idea_gen_fsc",
                            help="If the project contains any scala targets this specifies the "
                                   "fsc compiler should be enabled.")

    option_group.add_option(mkflag("java-encoding"), default="UTF-8",
                            dest="idea_gen_java_encoding",
                            help="[%default] Sets the file encoding for java files in this "
                                   "project.")
    option_group.add_option(mkflag("java-maximum-heap-size"),
                            dest="idea_gen_java_maximum_heap_size",
                            help="[%default] Sets the maximum heap size (in megabytes) for javac.")

  def __init__(self, *args, **kwargs):
    super(IdeaGen, self).__init__(*args, **kwargs)


    self.intellij_output_dir = os.path.join(self.gen_project_workdir, 'out')
    self.nomerge = not self.context.options.idea_gen_merge
    self.open = self.context.options.idea_gen_open
    self.bash = self.context.options.idea_gen_bash

    self.scala_language_level = _SCALA_VERSIONS.get(
      self.context.options.idea_scala_language_level, None)
    self.scala_maximum_heap_size = (
      self.context.options.idea_gen_scala_maximum_heap_size
      or self.context.config.get_option(self._IDEA_SCALA_MAX_HEAP_MB)
    )
    self.fsc = self.context.options.idea_gen_fsc

    self.java_encoding = self.context.options.idea_gen_java_encoding
    self.java_maximum_heap_size = (
      self.context.options.idea_gen_java_maximum_heap_size
      or self.context.config.get_option(self._IDEA_JAVA_MAX_HEAP_MB)
    )

    idea_version = _VERSIONS[self.context.options.idea_gen_version]
    self.project_template = os.path.join(_TEMPLATE_BASEDIR, 'project-%s.mustache' % idea_version)
    self.module_template = os.path.join(_TEMPLATE_BASEDIR, 'module-%s.mustache' % idea_version)

    self.project_filename = os.path.join(self.cwd, '%s.ipr' % self.project_name)
    self.module_filename = os.path.join(self.gen_project_workdir, '%s.iml' % self.project_name)

  def generate_project(self, project):
    def is_test(source_set):
      # Non test targets that otherwise live in test target roots (say a java_library), must
      # be marked as test for IDEA to correctly link the targets with the test code that uses
      # them. Therefore we check the base instead of the is_test flag.
      return source_set.source_base in SourceSet.TEST_BASES

    def create_content_root(source_set):
      root_relative_path = os.path.join(source_set.source_base, source_set.path) \
                           if source_set.path else source_set.source_base

      sources = TemplateData(
        path=root_relative_path,
        package_prefix=source_set.path.replace('/', '.') if source_set.path else None,
        is_test=is_test(source_set)
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
      extra_components=[],
    )

    outdir = os.path.abspath(self.intellij_output_dir)
    if not os.path.exists(outdir):
      os.makedirs(outdir)

    configured_project = TemplateData(
      root_dir=get_buildroot(),
      outdir=outdir,
      modules=[ configured_module ],
      java=TemplateData(
        encoding=self.java_encoding,
        maximum_heap_size=self.java_maximum_heap_size,
        jdk=self.java_jdk,
        language_level = 'JDK_1_%d' % self.java_language_level
      ),
      resource_extensions=list(project.resource_extensions),
      scala=scala,
      checkstyle_suppression_files=','.join(project.checkstyle_suppression_files),
      checkstyle_classpath=';'.join(project.checkstyle_classpath),
      debug_port=project.debug_port,
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
        Generator(pkgutil.get_data(__name__, self.project_template), project = configured_project))
    iml = self._generate_to_tempfile(
        Generator(pkgutil.get_data(__name__, self.module_template), module = configured_module))

    if not self.nomerge:
      # Get the names of the components we generated, and then delete the
      # generated files.  Clunky, but performance is not an issue, and this
      # is an easy way to get those component names from the templates.
      extra_project_components = self._get_components_to_merge(existing_project_components, ipr)
      extra_module_components =  self._get_components_to_merge(existing_module_components, iml)
      os.remove(ipr)
      os.remove(iml)

      # Generate again, with the extra components.
      ipr = self._generate_to_tempfile(Generator(pkgutil.get_data(__name__, self.project_template),
          project = configured_project.extend(extra_components = extra_project_components)))
      iml = self._generate_to_tempfile(Generator(pkgutil.get_data(__name__, self.module_template),
          module = configured_module.extend(extra_components = extra_module_components)))

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
    for _, _, files in os.walk(os.path.join(get_buildroot(), 'tests', 'resources')):
      resource_extensions.update(Project.extract_resource_extensions(files))

    return resource_extensions

  def _parse_xml_component_elements(self, path):
    """Returns a list of pairs (component_name, xml_fragment) where xml_fragment is the xml text of
    that <component> in the specified xml file."""
    if not os.path.exists(path):
      return []  # No existing components.
    dom = minidom.parse(path)
    # .ipr and .iml files both consist of <component> elements directly under a root element.
    return [ (x.getAttribute('name'), x.toxml()) for x in dom.getElementsByTagName('component') ]

  def _get_components_to_merge(self, mergable_components, path):
    """Returns a list of the <component> fragments in mergable_components that are not
    superceded by a <component> in the specified xml file.
    mergable_components is a list of (name, xml_fragment) pairs."""

    # As a convenience, we use _parse_xml_component_elements to get the
    # superceding component names, ignoring the generated xml fragments.
    # This is fine, since performance is not an issue.
    generated_component_names = set(
      [ name for (name, _) in self._parse_xml_component_elements(path) ])
    return [ x[1] for x in mergable_components if x[0] not in generated_component_names]
