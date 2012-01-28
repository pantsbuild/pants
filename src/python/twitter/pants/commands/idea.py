# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

__author__ = 'John Sirois'

from ide import Ide, Project
from twitter.pants.base.generator import Generator, TemplateData

import os
import shutil
import tempfile
import pkgutil
from xml.dom import minidom

_TEMPLATE_BASEDIR = 'idea/templates'

_VERSIONS = {
  '9': '10', # 9 and 10 are ipr/iml compatible
  '10': '10',
}

class Idea(Ide):
  """Creates IntelliJ IDEA projects for a set of BUILD targets."""

  __command__ = 'idea'

  def setup_parser(self, parser, args):
    Ide.setup_parser(self, parser, args)

    supported_versions = list(_VERSIONS.keys())
    supported_versions.sort()
    parser.add_option("-i", "--idea-version", dest = "version",
                      default = '10', type = "choice", choices = supported_versions,
                      help = "[%%default] The IntelliJ IDEA version the project configuration "
                      "should be generated for; can be one of: %s" % supported_versions)

    parser.add_option("-o", "--idea-project-file-dir", dest = "project_file_dir",
                      default = self.root_dir, help = "[%default] Specifies the directory to "
                      "output the generated project files to.")
    parser.add_option("--nomerge", action = "store_true", dest = "nomerge",
                      default = False, help = "Stomp any manual customizations in existing "
                      "Intellij IDEA configuration. If unspecified, manual customizations will be "
                      " merged into the new configuration.")
    parser.add_option("--idea-build-output-dir", dest = "intellij_output_dir",
                      default = os.path.join(self.root_dir, 'target/intellij/out'),
                      help = "[%default] Specifies the directory IntelliJ IDEA should use for its "
                      "own build output.")
    parser.add_option("-b", "--bash", action = "store_true", dest = "bash",
                      default = False, help = "Adds a bash facet to the generated project "
                      "configuration.")
    parser.add_option("-f", "--fsc", action = "store_true", dest = "fsc",
                      default = False, help = "If the project contains any scala targets this "
                      "specifies the fsc compiler should be enabled.")
    parser.add_option("-e", "--java-encoding", dest = "java_encoding",
                      default = "UTF-8", help = "[%default] Sets the file encoding for java files "
                      "in this project.")
    parser.epilog = """Creates an IntelliJ IDEA project appropriate for editing, debugging and
    testing the specified BUILD targets."""

  def __init__(self, root_dir, parser, argv):
    Ide.__init__(self, root_dir, parser, argv)

    idea_version = _VERSIONS[self.options.version]
    self.project_template = os.path.join(_TEMPLATE_BASEDIR, 'project-%s.mk' % idea_version)
    self.module_template = os.path.join(_TEMPLATE_BASEDIR, 'module-%s.mk' % idea_version)

    project_file_dir = os.path.abspath(self.options.project_file_dir)
    if not os.path.exists(project_file_dir):
      os.makedirs(project_file_dir)

    self.project_filename = os.path.join(project_file_dir, '%s.ipr' % self.project_name)
    self.module_filename = os.path.join(project_file_dir, '%s.iml' % self.project_name)

  def _generate_project_files(self, project, ivyfile, ivysettingsfile):
    def create_content_root(source_set):
      root_relative_path = os.path.join(source_set.source_base, source_set.path)
      return TemplateData(
        path = root_relative_path,
        sources = [ TemplateData(
          path = root_relative_path,
          package_prefix = source_set.path.replace('/', '.'),
          is_test = source_set.is_test,
        ) ],
        exclude_paths = [ os.path.join(source_set.source_base, x) for x in source_set.excludes ],
      )

    configured_module = TemplateData(
      root_dir = self.root_dir,
      path = self.module_filename,
      content_roots = [ create_content_root(source_set) for source_set in project.sources ],
      has_bash = self.options.bash,
      has_python = project.has_python,
      has_scala = project.has_scala,
      has_tests = project.has_tests,
      has_ivy = True,
      ivyfile = ivyfile,
      ivysettingsfile = ivysettingsfile,
      extra_components = [],
    )

    outdir = os.path.abspath(self.options.intellij_output_dir)
    if not os.path.exists(outdir):
      os.makedirs(outdir)

    configured_project = TemplateData(
      root_dir = self.root_dir,
      outdir = outdir,
      modules = [ configured_module ],
      java_encoding = self.options.java_encoding,
      resource_extensions = self._get_resource_extensions(project),
      has_scala = project.has_scala,
      scala_compiler_classpath = project.scala_compiler_classpath,
      scala = TemplateData(fsc = self.options.fsc) if project.has_scala else None,
      checkstyle_suppression_files = ','.join(project.checkstyle_suppression_files),
      checkstyle_classpath = ';'.join(project.checkstyle_classpath),
      extra_components = [],
    )

    if not self.options.nomerge:
      # Grab the existing components, which may include customized ones.
      existing_project_components = self._parse_xml_component_elements(self.project_filename)
      existing_module_components = self._parse_xml_component_elements(self.module_filename)

    # Generate (without merging in any extra components).
    ipr = self._generate_to_tempfile(
        Generator(pkgutil.get_data(__name__, self.project_template), project = configured_project))
    iml = self._generate_to_tempfile(
        Generator(pkgutil.get_data(__name__, self.module_template), module = configured_module))

    if not self.options.nomerge:
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

    return 0

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
    for _, _, files in os.walk(os.path.join(self.root_dir, 'tests', 'resources')):
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

