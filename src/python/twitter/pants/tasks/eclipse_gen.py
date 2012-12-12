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

from collections import defaultdict

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants import get_buildroot
from twitter.pants.base.generator import TemplateData, Generator
from twitter.pants.tasks.ide_gen import IdeGen


__author__ = 'John Sirois'


_TEMPLATE_BASEDIR = os.path.join('eclipse', 'templates')


_VERSIONS = {
  '3.5': '3.7', # 3.5-3.7 are .project/.classpath compatible
  '3.6': '3.7',
  '3.7': '3.7',
}


_SETTINGS = (
  'org.eclipse.core.resources.prefs',
  'org.eclipse.jdt.core.prefs',
  'org.eclipse.jdt.ui.prefs',
)


class EclipseGen(IdeGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    IdeGen.setup_parser(option_group, args, mkflag)

    supported_versions = sorted(list(_VERSIONS.keys()))
    option_group.add_option(mkflag("eclipse-version"), dest = "eclipse_gen_version",
                            default = '3.6', type = "choice", choices = supported_versions,
                            help = "[%%default] The Eclipse version the project "
                                   "configuration should be generated for; can be one of: "
                                   "%s" % supported_versions)

  def __init__(self, context):
    IdeGen.__init__(self, context)

    eclipse_version = _VERSIONS[context.options.eclipse_gen_version]
    self.project_template = os.path.join(_TEMPLATE_BASEDIR, 'project-%s.mustache' % eclipse_version)
    self.classpath_template = os.path.join(_TEMPLATE_BASEDIR, 'classpath-%s.mustache' % eclipse_version)
    self.apt_template = os.path.join(_TEMPLATE_BASEDIR, 'factorypath-%s.mustache' % eclipse_version)
    self.pydev_template = os.path.join(_TEMPLATE_BASEDIR, 'pydevproject-%s.mustache' % eclipse_version)
    self.debug_template = os.path.join(_TEMPLATE_BASEDIR, 'debug-launcher-%s.mustache' % eclipse_version)

    self.project_filename = os.path.join(self.cwd, '.project')
    self.classpath_filename = os.path.join(self.cwd, '.classpath')
    self.apt_filename = os.path.join(self.cwd, '.factorypath')
    self.pydev_filename = os.path.join(self.cwd, '.pydevproject')

  def generate_project(self, project):
    def linked_folder_id(path):
      return path.replace(os.path.sep, '.')

    def base_path(source_set):
      return os.path.join(source_set.root_dir, source_set.source_base)

    source_bases = {}
    def add_source_base(path, id):
      source_bases[path] = id

    for source_set in project.sources:
      add_source_base(base_path(source_set), linked_folder_id(source_set.source_base))
    if project.has_python:
      for source_set in project.py_sources:
        add_source_base(base_path(source_set), linked_folder_id(source_set.source_base))
      for source_set in project.py_libs:
        add_source_base(base_path(source_set), linked_folder_id(source_set.source_base))

    def create_source_template(base, includes=None, excludes=None):
      return TemplateData(
        base=source_bases[base],
        includes=includes or [],
        excludes=excludes or [],
        joined_includes = '|'.join(includes) if includes else '',
        joined_excludes = '|'.join(excludes) if excludes else '',
      )

    def create_sourcepath(base, sources):
      def normalize_path_pattern(path):
        return '%s/' % path if not path.endswith('/') else path

      includes = [normalize_path_pattern(src_set.path) for src_set in sources if src_set.path]
      excludes = []
      for source_set in sources:
        excludes.extend(normalize_path_pattern(exclude) for exclude in source_set.excludes)

      return create_source_template(base, includes, excludes)

    pythonpaths = []
    if project.has_python:
      for source_set in project.py_sources:
        pythonpaths.append(create_source_template(base_path(source_set)))
      for source_set in project.py_libs:
        lib_path = source_set.path if source_set.path.endswith('.egg') else '%s/' % source_set.path
        pythonpaths.append(create_source_template(base_path(source_set), includes=[lib_path]))

    source_bases_list = [{'path': path, 'id': id} for (path, id) in source_bases.items()]
    configured_project = TemplateData(
      name=self.project_name,
      has_python=project.has_python,
      has_scala=project.has_scala and not project.skip_scala,
      source_bases=source_bases_list,
      pythonpaths=pythonpaths,
      debug_port=project.debug_port,
    )

    outdir = os.path.abspath(os.path.join(self.work_dir, 'bin'))
    safe_mkdir(outdir)

    source_sets = defaultdict(OrderedSet) # base -> source_set
    for source_set in project.sources:
      source_sets[base_path(source_set)].add(source_set)
    sourcepaths = [create_sourcepath(base, sources) for base, sources in source_sets.items()]

    libs = []
    def add_jarlibs(classpath_entries):
      for classpath_entry in classpath_entries:
        jar = classpath_entry.jar
        source_jar = classpath_entry.source_jar
        libs.append(TemplateData(
          jar=os.path.relpath(jar, self.cwd),
          source_jar=os.path.relpath(source_jar, self.cwd) if source_jar else None
        ))
    add_jarlibs(project.internal_jars)
    add_jarlibs(project.external_jars)

    configured_classpath = TemplateData(
      sourcepaths=sourcepaths,
      has_tests=project.has_tests,
      libs=libs,
      has_scala = project.has_scala,
      outdir=os.path.relpath(outdir, get_buildroot()),
    )

    with safe_open(self.project_filename, 'w') as output:
      Generator(pkgutil.get_data(__name__, self.project_template),
                project=configured_project).write(output)

    with safe_open(self.classpath_filename, 'w') as output:
      Generator(pkgutil.get_data(__name__, self.classpath_template),
                classpath=configured_classpath).write(output)

    debug_filename = os.path.join(self.work_dir, 'Debug on port %d.launch' % project.debug_port)
    with safe_open(debug_filename, 'w') as output:
      Generator(pkgutil.get_data(__name__, self.debug_template),
                project=configured_project).write(output)

    for resource in _SETTINGS:
      with safe_open(os.path.join(self.cwd, '.settings', resource), 'w') as prefs:
        prefs.write(pkgutil.get_data(__name__, os.path.join('eclipse', 'files', resource)))

    factorypath = TemplateData(
      project_name=self.project_name,

      # The easiest way to make sure eclipse sees all annotation processors is to put all libs on
      # the apt factorypath - this does not seem to hurt eclipse performance in any noticeable way.
      jarpaths=["('%s', %s)" % (lib.jar, "'%s'" % lib.source_jar if lib.source_jar else 'None') for lib in libs]
    )
    with open(self.apt_filename, 'w') as output:
      Generator(pkgutil.get_data(__name__, self.apt_template),
                factorypath =factorypath).write(output)

    if project.has_python:
      with safe_open(self.pydev_filename, 'w') as output:
        Generator(pkgutil.get_data(__name__, self.pydev_template),
                  project=configured_project).write(output)
    else:
      if os.path.exists(self.pydev_filename):
        os.remove(self.pydev_filename)

    print('\nGenerated project at %s%s' % (self.work_dir, os.sep))
