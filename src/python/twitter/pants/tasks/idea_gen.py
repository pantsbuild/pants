# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================
import os
import pkgutil
import shutil
import tempfile

from xml.dom import minidom

from twitter.common.dirutil import safe_mkdir

from twitter.pants import get_buildroot
from twitter.pants.base.generator import TemplateData, Generator
from twitter.pants.tasks.ide_gen import IdeGen, Project


__author__ = 'John Sirois'


_TEMPLATE_BASEDIR = 'idea/templates'


_VERSIONS = {
  '9': '11', # 9 and 11 are ipr/iml compatible
  '10': '11', # 9 and 11 are ipr/iml compatible
  '11': '11'
}


class IdeaGen(IdeGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    IdeGen.setup_parser(option_group, args, mkflag)

    supported_versions = sorted(list(_VERSIONS.keys()))
    option_group.add_option(mkflag("idea-version"), dest = "idea_gen_version",
                            default = '11', type = "choice", choices = supported_versions,
                            help = "[%%default] The IntelliJ IDEA version the project "
                                   "configuration should be generated for; can be one of: " \
                                   "%s" % supported_versions)

    option_group.add_option(mkflag("merge"), mkflag("merge", negate=True), default = True,
                            action="callback", callback=mkflag.set_bool, dest = "idea_gen_merge",
                            help = "[%default] Merge any manual customizations in existing "
                                   "Intellij IDEA configuration. If False, manual customizations "
                                   "will be over-written.")

    option_group.add_option(mkflag("open"), mkflag("open", negate=True), default = True,
                            action="callback", callback=mkflag.set_bool, dest = "idea_gen_open",
                            help = "[%default] Attempts top open the generated project in IDEA.")

    option_group.add_option(mkflag("bash"), mkflag("bash", negate=True), default = False,
                            action="callback", callback=mkflag.set_bool, dest = "idea_gen_bash",
                            help = "Adds a bash facet to the generated project configuration.")
    option_group.add_option(mkflag("fsc"), mkflag("fsc", negate=True), default = False,
                            action="callback", callback=mkflag.set_bool, dest = "idea_gen_fsc",
                            help = "If the project contains any scala targets this specifies the "
                                   "fsc compiler should be enabled.")
    option_group.add_option(mkflag("java-encoding"), default = "UTF-8",
                            dest = "idea_gen_java_encoding",
                            help = "[%default] Sets the file encoding for java files in this "
                                   "project.")

  def __init__(self, context):
    IdeGen.__init__(self, context)


    self.intellij_output_dir = os.path.join(self.work_dir, 'out')
    self.nomerge = not context.options.idea_gen_merge
    self.open = context.options.idea_gen_open
    self.bash = context.options.idea_gen_bash
    self.fsc = context.options.idea_gen_fsc
    self.java_encoding = context.options.idea_gen_java_encoding

    idea_version = _VERSIONS[context.options.idea_gen_version]
    self.project_template = os.path.join(_TEMPLATE_BASEDIR, 'project-%s.mustache' % idea_version)
    self.module_template = os.path.join(_TEMPLATE_BASEDIR, 'module-%s.mustache' % idea_version)

    self.project_filename = os.path.join(self.cwd, '%s.ipr' % self.project_name)
    self.module_filename = os.path.join(self.work_dir, '%s.iml' % self.project_name)

  def generate_project(self, project):
    def create_content_root(source_set):
      root_relative_path = os.path.join(source_set.source_base, source_set.path) \
                           if source_set.path else source_set.source_base
      return TemplateData(
        path = root_relative_path,
        sources = [ TemplateData(
          path = root_relative_path,
          package_prefix = source_set.path.replace('/', '.') if source_set.path else None,
          is_test = source_set.is_test,
        ) ],
        exclude_paths = [ os.path.join(source_set.source_base, x) for x in source_set.excludes ],
      )

    content_roots = [create_content_root(source_set) for source_set in project.sources]
    if project.has_python:
      content_roots.extend(create_content_root(source_set) for source_set in project.py_sources)

    configured_module = TemplateData(
      root_dir = get_buildroot(),
      path = self.module_filename,
      content_roots = content_roots,
      has_bash = self.bash,
      has_python = project.has_python,
      has_scala = project.has_scala,
      has_tests = project.has_tests,
      internal_jars = [cp_entry.jar for cp_entry in project.internal_jars],
      internal_source_jars = [cp_entry.source_jar for cp_entry in project.internal_jars
                              if cp_entry.source_jar],
      external_jars = [cp_entry.jar for cp_entry in project.external_jars],
      external_source_jars = [cp_entry.source_jar for cp_entry in project.external_jars
                              if cp_entry.source_jar],
      extra_components = [],
    )

    outdir = os.path.abspath(self.intellij_output_dir)
    if not os.path.exists(outdir):
      os.makedirs(outdir)

    configured_project = TemplateData(
      root_dir = get_buildroot(),
      outdir = outdir,
      modules = [ configured_module ],
      java_encoding = self.java_encoding,
      resource_extensions = self._get_resource_extensions(project),
      has_scala = project.has_scala,
      scala_compiler_classpath = project.scala_compiler_classpath,
      scala = TemplateData(fsc = self.fsc) if project.has_scala else None,
      checkstyle_suppression_files = ','.join(project.checkstyle_suppression_files),
      checkstyle_classpath = ';'.join(project.checkstyle_classpath),
      debug_port=project.debug_port,
      extra_components = [],
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

    shutil.move(ipr, self.project_filename)
    shutil.move(iml, self.module_filename)

    print('\nGenerated project at %s%s' % (self.work_dir, os.sep))

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

