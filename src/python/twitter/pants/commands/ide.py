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

from . import Command

from twitter.common.collections import OrderedSet
from twitter.common.config import Properties
from twitter.pants import (
  extract_jvm_targets,
  get_buildroot,
  has_sources,
  is_apt,
  is_java,
  is_scala,
  is_test
)
from twitter.pants.base import Address, Target
from twitter.pants.targets import JavaLibrary, ScalaLibrary, ExportableJvmLibrary
from twitter.pants.tasks.binary_utils import profile_classpath
from twitter.pants.ant import AntBuilder
from twitter.pants.ant.ide import extract_target

import os
import re
import traceback

class Ide(Command):
  """Creates IDE projects for a set of BUILD targets."""

  PROFILE_DIR = os.path.join(get_buildroot(), 'build-support/profiles')
  SCALA_PROFILE_PARSER = re.compile('scala-compile-(.+).ivy.xml')

  def setup_parser(self, parser, args):
    parser.set_usage("%%prog %s ([spec]...)" % self.__class__.__command__)
    parser.add_option("-d", "--directory", action="store_true", dest="is_directory_list",
                      default=False, help="Specifies specs should be treated as plain paths, "
                      "in which case all targets found in all BUILD files under the paths will be "
                      "used to create the IDEA project configuration.")
    parser.add_option("-c", "--clean", action="store_true", dest="clean",
                      default=False, help="Triggers a clean build of any codegen targets.")
    parser.add_option("-n", "--project-name", dest="project_name",
                      default="project",
                      help="[%default] Specifies the name to use for the generated project.")

    def set_bool(option, opt_str, value, parser):
      setattr(parser.values, option.dest, not opt_str.startswith("--no"))

    parser.add_option("-p", "--python", "--no-python",
                      action="callback", callback=set_bool, dest='python', default=False,
                      help="[%default] Adds python support to the generated project configuration.")
    parser.add_option("--java", "--no-java",
                      action="callback", callback=set_bool, dest='java', default=True,
                      help="[%default] Includes java sources in the project; otherwise compiles "
                      "them and adds them to the project classpath.")
    parser.add_option("--scala", "--no-scala",
                      action="callback", callback=set_bool, dest='scala', default=True,
                      help="[%default] Includes scala sources in the project; otherwise compiles "
                      "them and adds them to the project classpath.")


    profiles = os.listdir(Ide.PROFILE_DIR)
    self.scala_compiler_profile_by_version = {}
    for profile in profiles:
      match = Ide.SCALA_PROFILE_PARSER.match(profile)
      if match:
        version = match.group(1)
        self.scala_compiler_profile_by_version[version] = 'scala-compile-%s' % version
    supported_versions = sorted(self.scala_compiler_profile_by_version.keys())
    parser.add_option("--scala-version", dest='scala_version', default='2.8.1', type = "choice",
                      choices = supported_versions, help="[%default] Sets the scala version.")

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    self.project_name = self.options.project_name
    self.scala_compiler_profile = self.scala_compiler_profile_by_version[self.options.scala_version]

    addresses = self._parse_addresses() if self.args else Command.scan_addresses(root_dir)
    self.targets = [ Target.get(address) for address in addresses ]

  def _parse_addresses(self):
    addresses = OrderedSet()
    for spec in self.args:
      try:
        if self.options.is_directory_list:
          for address in Command.scan_addresses(self.root_dir, spec):
            addresses.add(address)
        else:
          addresses.add(Address.parse(self.root_dir, spec))
      except:
        self.error("Problem parsing spec %s: %s" % (spec, traceback.format_exc()))
    return addresses

  def execute(self):
    jvm_targets = OrderedSet(extract_jvm_targets(self.targets))
    if not jvm_targets:
      raise Exception("Only jvm targets currently handled and none found in: %s" % self.targets)

    skip_java = not self.options.java
    skip_scala = not self.options.scala

    checkstyle_suppression_files = self._load_checkstyle_suppressions()
    project = Project(self.project_name,
                      self.options.python,
                      skip_java,
                      skip_scala,
                      self.root_dir,
                      checkstyle_suppression_files,
                      jvm_targets)
    all_targets = project.configure(self.scala_compiler_profile)

    foil = list(all_targets)[0]
    def is_cp(target):
      return target.is_codegen \
             or is_apt(target) \
             or (skip_java and is_java(target)) \
             or (skip_scala and is_scala(target))

    ide_target = foil.do_in_context(lambda: extract_target(all_targets, is_cp))

    ivyfile, ivysettingsfile = self._generate_ivy(ide_target)
    return self._generate_project_files(project, ivyfile, ivysettingsfile)

  def _generate_ivy(self, ide_target):
    jvmbuilder = AntBuilder(self.error, self.root_dir)

    antargs = []
    if self.options.clean:
      antargs.extend([ 'clean-all', 'compile' ])

    _, ivyfile, _ = jvmbuilder.generate_and_build([ide_target], antargs, name = self.project_name)
    return ivyfile, os.path.join(self.root_dir, 'build-support', 'ivy', 'ivysettings.xml')

  def _load_checkstyle_suppressions(self):
    with open(os.path.join(self.root_dir, 'build.properties')) as build_props:
      return Ide._find_checkstyle_suppressions(build_props, self.root_dir)

  @staticmethod
  def _find_checkstyle_suppressions(props, root_dir):
    props = Properties.load(props)

    # Magic - we know the root.dir property is defined elsewhere, so we seed it.
    props['root.dir'] = root_dir

    def resolve_props(value):
      def replace_symbols(matchobj):
        return props[matchobj.group(1)]

      symbol_parser = re.compile("\${([^}]+)\}")
      while symbol_parser.match(value):
        value = symbol_parser.sub(replace_symbols, value)
      return value

    files = resolve_props(props['checkstyle.suppression.files'])
    return files.split(',')

  def _generate_project_files(self, project, ivyfile, ivysettingsfile):
    """Generates project files that configure the IDE given a configured project and ivy files."""

    raise NotImplementedError('Subclasses must implement this method')

class SourceSet(object):
  """Models a set of source files."""

  def __init__(self, root_dir, source_base, path, is_test):
    """root_dir: the full path to the root directory of the project containing this source set
    source_base: the relative path from root_dir to the base of this source set
    path: the relative path from the source_base to the base of the sources in this set
    is_test: true iff the sources contained by this set implement test cases"""

    self.root_dir = root_dir
    self.source_base = source_base
    self.path = path
    self.is_test = is_test
    self._excludes = []

  @property
  def excludes(self):
    """Paths relative to self.path that are excluded from this source set."""

    return self._excludes

class Project(object):
  """Models a generic IDE project that is comprised of a set of BUILD targets."""

  @staticmethod
  def extract_resource_extensions(resources):
    """Returns the set of unique extensions (including the .) from the given resource files."""

    if resources:
      for resource in resources:
        _, ext = os.path.splitext(resource)
        yield ext

  def __init__(self, name, has_python, skip_java, skip_scala, root_dir,
               checkstyle_suppression_files, targets):
    """Creates a new, unconfigured, Project based at root_dir and comprised of the sources visible
    to the given targets."""

    self.name = name
    self.root_dir = root_dir
    self.targets = OrderedSet(targets)

    self.sources = []
    self.resource_extensions = set()

    self.has_python = has_python
    self.skip_java = skip_java
    self.skip_scala = skip_scala
    self.has_scala = False
    self.has_tests = False

    self.checkstyle_suppression_files = checkstyle_suppression_files # Absolute paths.

  def configure(self, scala_compiler_profile):
    """Configures this project's source sets returning the full set of targets the project is
    comprised of.  The full set can be larger than the initial set of targets when any of the
    initial targets only has partial ownership of its source set's directories."""

    # TODO(John Sirois): much waste lies here, revisit structuring for more readable and efficient
    # construction of source sets and excludes ... and add a test!

    analyzed = OrderedSet()
    targeted = set()

    def source_target(target):
      return has_sources(target) \
          and (not target.is_codegen
               and not (self.skip_java and is_java(target))
               and not (self.skip_scala and is_scala(target)))

    def configure_source_sets(relative_base, sources, is_test):
      absolute_base = os.path.join(self.root_dir, relative_base)
      paths = set([ os.path.dirname(source) for source in sources])
      for path in paths:
        absolute_path = os.path.join(absolute_base, path)
        if absolute_path not in targeted:
          targeted.add(absolute_path)
          self.sources.append(SourceSet(self.root_dir, relative_base, path, is_test))

    def find_source_basedirs(target):
      dirs = set()
      if source_target(target):
        absolute_base = os.path.join(self.root_dir, target.target_base)
        dirs.update([ os.path.join(absolute_base, os.path.dirname(source))
                      for source in target.sources ])
      return dirs

    def configure_target(target):
      if target not in analyzed:
        analyzed.add(target)

        self.has_scala = not self.skip_scala and (self.has_scala or is_scala(target))

        if isinstance(target, JavaLibrary) or isinstance(target, ScalaLibrary):
          # TODO(John Sirois): this does not handle test resources, make test resources 1st class
          # in ant build and punch this through to pants model
          resources = set()
          if target.resources:
            resources.update(target.resources)
          if resources:
            self.resource_extensions.update(Project.extract_resource_extensions(resources))
            configure_source_sets(ExportableJvmLibrary.RESOURCES_BASE_DIR,
                                  resources,
                                  is_test = False)

        if target.sources:
          test = is_test(target)
          self.has_tests = self.has_tests or test
          configure_source_sets(target.target_base, target.sources, is_test = test)

        # Other BUILD files may specify sources in the same directory as this target.  Those BUILD
        # files might be in parent directories (globs('a/b/*.java')) or even children directories if
        # this target globs children as well.  Gather all these candidate BUILD files to test for
        # sources they own that live in the directories this targets sources live in.
        target_dirset = find_source_basedirs(target)
        candidates = Target.get_all_addresses(target.address.buildfile)
        for ancestor in target.address.buildfile.ancestors():
          candidates.update(Target.get_all_addresses(ancestor))
        for sibling in target.address.buildfile.siblings():
          candidates.update(Target.get_all_addresses(sibling))
        for descendant in target.address.buildfile.descendants():
          candidates.update(Target.get_all_addresses(descendant))

        def is_sibling(target):
          return source_target(target) and target_dirset.intersection(find_source_basedirs(target))

        return filter(is_sibling, [ Target.get(a) for a in candidates if a != target.address ])

    for target in self.targets:
      target.walk(configure_target, predicate = source_target)

    self._configure_profiles(scala_compiler_profile)

    # We need to figure out excludes, in doing so there are 2 cases we should not exclude:
    # 1.) targets depend on A only should lead to an exclude of B
    # A/BUILD
    # A/B/BUILD
    #
    # 2.) targets depend on A and C should not lead to an exclude of B (would wipe out C)
    # A/BUILD
    # A/B
    # A/B/C/BUILD
    #
    # 1 approach: build set of all paths and parent paths containing BUILDs our targets depend on -
    # these are unexcludable

    unexcludable_paths = set()
    for source_set in self.sources:
      parent = os.path.join(self.root_dir, source_set.source_base, source_set.path)
      while True:
        unexcludable_paths.add(parent)
        parent, dir = os.path.split(parent)
        # no need to add the repo root or above, all source paths and extra paths are children
        if parent == self.root_dir:
          break

    for source_set in self.sources:
      paths = set()
      source_base = os.path.join(self.root_dir, source_set.source_base)
      for root, dirs, _ in os.walk(os.path.join(source_base, source_set.path)):
        if dirs:
          paths.update([ os.path.join(root, dir) for dir in dirs ])
      unused_children = paths - targeted
      if unused_children:
        for child in unused_children:
          if child not in unexcludable_paths:
            source_set.excludes.append(os.path.relpath(child, source_base))

    targets = OrderedSet()
    for target in self.targets:
      target.walk(lambda target: targets.add(target), source_target)
    targets.update(analyzed - targets)
    return targets

  def _configure_profiles(self, scala_compiler_profile):
    self.checkstyle_classpath = profile_classpath('checkstyle')
    self.scala_compiler_classpath = []
    if self.has_scala:
      self.scala_compiler_classpath.extend(profile_classpath(scala_compiler_profile))
