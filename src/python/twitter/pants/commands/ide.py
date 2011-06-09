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
from twitter.pants import has_sources, extract_jvm_targets, is_scala, is_test
from twitter.pants.base import Address, Target
from twitter.pants.targets import JavaLibrary, ScalaLibrary, ExportableJvmLibrary
from twitter.pants.ant import AntBuilder
from twitter.pants.ant.lib import (
  TRANSITIVITY_NONE,
  TRANSITIVITY_SOURCES,
  TRANSITIVITY_TESTS,
  TRANSITIVITY_ALL,
)

import os
import traceback

_TRANSITIVITY_CHOICES = [
  TRANSITIVITY_NONE,
  TRANSITIVITY_SOURCES,
  TRANSITIVITY_TESTS,
  TRANSITIVITY_ALL
]
_VALID_TRANSITIVITIES = set(_TRANSITIVITY_CHOICES)

class Ide(Command):
  """Creates IDE projects for a set of BUILD targets."""

  def setup_parser(self, parser):
    parser.set_usage("%prog idea ([spec]...)")
    parser.add_option("-d", "--directory", action = "store_true", dest = "is_directory_list",
                      default = False, help = "Specifies specs should be treated as plain paths, "
                      "in which case all targets found in all BUILD files under the paths will be "
                      "used to create the IDEA project configuration.")
    parser.add_option("-c", "--clean", action = "store_true", dest = "clean",
                      default = False, help = "Triggers a clean build of any codegen targets.")
    parser.add_option("-t", "--ide-transitivity", dest = "ide_transitivity", type = "choice",
                      choices = _TRANSITIVITY_CHOICES, default = TRANSITIVITY_ALL,
                      help = "[%%default] Specifies IDE dependencies should be transitive for one "
                             "of: %s" % _TRANSITIVITY_CHOICES)
    parser.add_option("-n", "--project-name", dest = "project_name",
                      default = "project",
                      help = "[%default] Specifies the name to use for the generated project.")
    parser.add_option("-p", "--python", action = "store_true", dest = "python",
                      default = False, help = "Adds python support to the generated project "
                      "configuration.")

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    self.project_name = self.options.project_name
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

    project = Project(self.project_name, self.options.python, self.root_dir, jvm_targets)
    all_targets = project.configure()
    ivyfile, ivysettingsfile = self._generate_ivy(all_targets)
    self._generate_project_files(project, ivyfile, ivysettingsfile)

  def _generate_ivy(self, targets):
    jvmbuilder = AntBuilder(self.error,
                            self.root_dir,
                            is_ide = True,
                            ide_transitivity = self.options.ide_transitivity)

    antargs = []
    if self.options.clean:
      antargs.extend([ 'clean-all', 'compile' ])

    _, ivyfile, _ = jvmbuilder.generate_and_build(targets, antargs, name = self.project_name)
    return ivyfile, os.path.join(self.root_dir, 'build-support', 'ivy', 'ivysettings.xml')

  def _generate_project_files(self, project, ivyfile, ivysettingsfile):
    """Generates project files that configure the IDE given a configured project and ivy files."""

    raise Exception('Subclasses must implement this method')

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

  def __init__(self, name, has_python, root_dir, targets):
    """Creates a new, unconfigured, Project based at root_dir and comprised of the sources visible
    to the given targets."""

    self.name = name
    self.root_dir = root_dir
    self.targets = OrderedSet(targets)

    self.sources = []
    self.resource_extensions = set()

    self.has_python = has_python
    self.has_scala = False
    self.has_tests = False
    self.extra_checkstyle_suppression_files = []  # Paths relative to the build root.

  def configure(self):
    """Configures this project's source sets returning the full set of targets the project is
    comprised of.  The full set can be larger than the initial set of targets when any of the
    initial targets only has partial ownership of its parent directory source set."""

    analyzed = OrderedSet()
    targeted = set()

    def accept_target(target):
      return has_sources(target) and not target.is_codegen

    def configure_source_sets(relative_base, sources, is_test):
      absolute_base = os.path.join(self.root_dir, relative_base)
      paths = set([ os.path.dirname(source) for source in sources])
      for path in paths:
        absolute_path = os.path.join(absolute_base, path)
        if absolute_path not in targeted:
          targeted.add(absolute_path)
          self.sources.append(SourceSet(self.root_dir, relative_base, path, is_test))

    def configure_target(target):
      if target not in analyzed:
        analyzed.add(target)

        self.has_scala = self.has_scala or is_scala(target)

        if isinstance(target, JavaLibrary) or isinstance(target, ScalaLibrary):
          # TODO(John Sirois): this does not handle test resources, make test resources 1st class
          # in ant build and punch this through to pants model
          resources = set()
          if target.resources:
            resources.update(target.resources)
          if target.binary_resources:
            resources.update(target.binary_resources)
          if resources:
            self.resource_extensions.update(Project.extract_resource_extensions(resources))
            configure_source_sets(ExportableJvmLibrary.RESOURCES_BASE_DIR, resources, is_test = False)

        if target.sources:
          test = is_test(target)
          self.has_tests = self.has_tests or test
          configure_source_sets(target.target_base, target.sources, is_test = test)

        siblings = Target.get_all_addresses(target.address.buildfile)
        return filter(accept_target, [ Target.get(a) for a in siblings if a != target.address ])

    for target in self.targets:
      target.walk(configure_target, predicate = accept_target)

    for source_set in self.sources:
      paths = set()
      source_base = os.path.join(self.root_dir, source_set.source_base)
      for root, dirs, _ in os.walk(os.path.join(source_base, source_set.path)):
        if dirs:
          paths.update([ os.path.join(root, dir) for dir in dirs ])
      unused_children = paths - targeted
      if unused_children and paths != unused_children:
        source_set.excludes.extend(os.path.relpath(child, source_base) for child in unused_children)

    targets = OrderedSet()
    for target in self.targets:
      target.walk(lambda target: targets.add(target), has_sources)
    targets.update(analyzed - targets)
    return targets
