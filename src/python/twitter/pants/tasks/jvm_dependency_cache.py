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

__author__ = 'Mark C. Chu-Carroll'

import os
from collections import defaultdict

from twitter.pants.targets.jar_dependency import JarDependency
from twitter.pants.targets.jvm_target import JvmTarget
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.scala.zinc_analysis_file import ZincAnalysisCollection


class JvmDependencyCache(object):
  """
  Class which computes and stores information about the compilation dependencies
  of targets for jvm-based languages.

  The behavior of this is determined by flags set in the compilation task's context.
  The flags (set by command-line options) are:
  - check_missing_deps: the master flag, which determines whether the dependency checks should
     be run at all.
  - check_intransitive_deps: a flag which determines whether or not to generate errors about
    intransitive dependency errors, where a target has a dependency on another target which
    it doesn't declare, but which is part of its transitive dependency graph. If this is set
    to "none", intransitive errors won't be reported. If "warn", then it will print warning
    messages, but will not cause the build to fail, and will not populate build products with the errors.
    If "error", then the messages will be printed, build products populated, and the build will fail.
  - check_unnecessary_deps: if set to True, then warning messages will be printed about dependencies
    that are declared, but not actually required.
  """

  @staticmethod
  def init_product_requirements(task):
    """
    Set the compilation product requirements that are needed for dependency analysis.

    Parameters:
      task: the task whose products should be set.
    """
    task._computed_jar_products = False
    task.context.products.require('classes')
    task.context.products.require("ivy_jar_products")

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    """
    Set up command-line options for dependency checking.
    Any jvm compilation task that wants to use dependency analysis can call this from
    its setup_parser method to add the appropriate options for dependency testing.

    See scala_compile.py for an example.
    """
    option_group.add_option(mkflag("check-missing-deps"), mkflag("check-missing-deps", negate=True),
                            dest="scala_check_missing_deps",
                            action="callback", callback=mkflag.set_bool,
                            default=False,
                            help="[%default] Check for undeclared dependencies in scala code")

    # This flag should eventually be removed once code is in compliance.
    option_group.add_option(mkflag("check-missing-intransitive-deps"),
                            type="choice",
                            action='store',
                            dest='scala_check_intransitive_deps',
                            choices=['none', 'warn', 'error'],
                            default='none',
                            help="[%default] Enable errors for undeclared deps that don't cause compilation" \
                                  "errors, because the dependencies are provided transitively.")
    option_group.add_option(mkflag("check-unnecessary-deps"),
                            mkflag("check-unnecessary-deps", negate=True),
                            dest='scala_check_unnecessary_deps',
                            action="callback", callback=mkflag.set_bool,
                            default=False,
                            help="[%default] Enable warnings for declared dependencies that are not needed.")

  def __init__(self, context, targets, all_analysis_files):
    """
    Parameters:
      context: The task context instance.
      targets: The set of targets to analyze. These should all be target types that
               inherit from jvm_target, and contain source files that will be compiled into
               jvm class files.
      all_analysis_files: The analysis files of the targets to analyze, and all their deps.
    """
    self.all_analysis_files = all_analysis_files
    self.zinc_analysis_collection = None
    self.context = context
    self.check_missing_deps = self.context.options.scala_check_missing_deps
    self.check_intransitive_deps = self.context.options.scala_check_intransitive_deps
    self.check_unnecessary_deps = self.context.options.scala_check_unnecessary_deps
    self.targets = targets

    # Maps used by the zinc cache variant of dependency analysis.

    # Mapping from target to jars that ivy reports the target provides.
    self.ivy_jars_by_target = defaultdict(set)
    # Mapping from jar to targets that provide those jars; inverse of ivy_jars_by_target.
    self.ivy_targets_by_jar = defaultdict(set)
    # Mapping from targets to the set of classes that those targets depend on.
    self.zinc_class_deps_by_target = defaultdict(set)
    # Mapping from targets to the classes provided by a source file in the target.
    self.zinc_classes_provided_by_target = defaultdict(set)
    # Inverse of classes_provided_by_target: map from classes to the target that provides them.
    self.zinc_targets_by_provided_class = defaultdict(set)
    # Mapping from targets to the jar library targets that they depend on.
    self.zinc_jardeps_by_target = defaultdict(set)

    # The result of the analysis: a computed map from each jvm target to the set of targets
    # that it depends on.
    self.computed_src_deps = None
    # Computed map from each jvm target to the set of jar targets that it includes
    self.computed_jar_deps = None

  def _get_jardep_dependencies(self, target):
    """
    Walks the dependency graph for a target, getting the transitive closure of
    its set of declared jar dependencies.
    """
    result = []
    target.walk(lambda t: self._walk_jardeps(t, result))
    return set(result)

  def _walk_jardeps(self, target, result):
    """
    A dependency walker for extracting jar dependencies from the dependency graph
    of targets in this compilation task.
    """
    if isinstance(target, JarDependency):
      result.append(target)
    if isinstance(target, JvmTarget):
      result.extend(target.jar_dependencies)

  def _compute_jardep_contents(self):
    """
    Compute the information needed by deps analysis for the set of classes that come from
    jars in jar_dependency targets. This is messier that it should be, because of
    the strange way that jar_dependency targets are treated by pants.

    Returns: a pair of maps, (jars_by_target, targets_by_jar) describing the mappings between jars
       and the targets that contain those jars.
    """

    # Get a list of all of the jar dependencies declared by the build targets.
    found_jar_deps = set()
    for jt in self.targets:
      jars = self._get_jardep_dependencies(jt)
      found_jar_deps = found_jar_deps.union(jars)
    jardeps_by_id = {}
    for jardep in found_jar_deps:
      jardeps_by_id[(jardep.org, jardep.name)] = jardep

    # Using the ivy reports in the build products, compute a list of
    # actual jar dependencies.
    ivy_products = self.context.products.get("ivy_jar_products").get("ivy")
    ivy_jars_by_target = defaultdict(set)
    ivy_targets_by_jar = defaultdict(set)
    for ivy_report_list in ivy_products.values():
      for report in ivy_report_list:
        for ref in report.modules_by_ref:
          target_key = (ref.org, ref.name)
          if target_key in jardeps_by_id:
            jardep_target = jardeps_by_id[target_key]
            for jar in report.modules_by_ref[ref].artifacts:
              ivy_jars_by_target[jardep_target].add(jar.path)
              ivy_targets_by_jar[jar.path].add(jardep_target)
    return ivy_jars_by_target, ivy_targets_by_jar

  def _normalize_source_path(self, target, src):
    """
    Given a target and a source file path specified by that target, produce a normalized
    path for the source file that matches the pathname used in the zinc analysis files.
    """
    return os.path.join(target.target_base, src)


  def get_compilation_dependencies(self):
    """
    Computes a map from the source files in a target to class files that the source file
    depends on.

    Note: this code currently relies on the relations report generated by the zinc incremental
    scala compiler. If other languages/compilers want to use this code, they need to provide
    a similar report. See zinc_analysis_file.py for details about the information
    needed by this analysis.

    Parameters:
      targets: a list of the targets from the current compile run whose
         dependencies should be analyzed.
    Returns: a target-to-target mapping from targets to targets that they depend on.
       If this was already computed, return the already computed result.
    """
    if self.computed_src_deps is not None:
      return self.computed_src_deps, self.computed_jar_deps
    self.computed_src_deps = defaultdict(set)
    self.computed_jar_deps = defaultdict(set)
    self.zinc_analysis_collection = ZincAnalysisCollection(self.all_analysis_files)

    # Use data about targets to convert the zinc cache stuff into target -> target pendencies.

    # First, get some basic source target information: a map from sources to the targets that
    # include them, and a map from classes to the targets that provide them.
    targets_by_source = defaultdict(set)
    for target in self.targets:
      for src in target.sources:
        srcpath = self._normalize_source_path(target, src)
        classes = self.zinc_analysis_collection.class_names[srcpath]
        self.zinc_classes_provided_by_target[target] |= classes
        for cl in classes:
          self.zinc_targets_by_provided_class[cl].add(target)
        targets_by_source[src].add(target)

    # Detect overlapping targets: if a source file is included in more
    # than one target, then we have an overlap.
    overlapping_sources = set()
    for s in targets_by_source:
      if len(targets_by_source[s]) > 1:
        overlapping_sources.add(s)
        print "Error: source file %s included in multiple targets %s" % (s, targets_by_source[s])

    # Then generate a map from targets to the classes that they depend on.
    for target in self.targets:
      for src in target.sources:
        srcpath = self._normalize_source_path(target, src)
        self.zinc_class_deps_by_target[target] |= self.zinc_analysis_collection.external_deps[srcpath]

    # Join the two maps, to get a list of target -> target deps
    for fromtarget in self.zinc_class_deps_by_target:
      depclasses = self.zinc_class_deps_by_target[fromtarget]
      for cl in depclasses:
        if cl in self.zinc_targets_by_provided_class:
          totarget = self.zinc_targets_by_provided_class[cl]
          self.computed_src_deps[fromtarget] |= totarget

    # Figure out which jars are in which targets, and then use with the zinc
    # binary dependencies to figure out which jars belong to which targets.

    (self.ivy_jars_by_target, self.ivy_targets_by_jar) = self._compute_jardep_contents()

    for target in self.targets:
      for src in target.sources:
        srcpath = self._normalize_source_path(target, src)
        jardeps = self.zinc_analysis_collection.binary_deps[srcpath]
        for j in jardeps:
          self.computed_jar_deps[target] |= self.ivy_targets_by_jar[j]

    return self.computed_src_deps, self.computed_jar_deps


  def get_dependency_blame(self, from_target, to_target):
    """
    Figures out why target A depends on target B according the the dependency analysis.
    Generates a tuple which can be used to generate a message like:
     "*from_target* depends on *to_target* because *from_target*'s source file X
      depends on *to_target*'s class Y."
     Returns: a pair of (source, class) where:
       source is the name of a source file in "from" that depends on something
          in "to".
       class is the name of the class that source1 depends on.
       If no dependency data could be found to support the dependency,
       returns (None, None)
    """
    # iterate over the sources in the from target.
    for source in from_target.sources:
      # for each class that the source depends on:
      srcpath = self._normalize_source_path(from_target, source)
      for cl in self.zinc_analysis_collection.external_deps[srcpath]:
        targets_providing = self.zinc_targets_by_provided_class[cl]
        if to_target in targets_providing:
          return source, cl
    return None, None

  def check_undeclared_dependencies(self):
    """
    Performs the undeclared dependencies/overdeclared dependencies checks,
    generating warnings/error messages and (depending on flag settings),
    setting build products for the detected errors.
    """
    if not self.check_missing_deps:
        return
    (deps_by_target, jar_deps_by_target) = self.get_compilation_dependencies()
    found_missing_deps = False
    for target in deps_by_target:
      computed_deps = deps_by_target[target]
      computed_jar_deps = jar_deps_by_target[target]

      # Make copies of the computed deps. Then we'll walk the declared deps,
      # removing everything that was declared; what's left are the undeclared deps.
      undeclared_deps = computed_deps.copy()
      undeclared_jar_deps = computed_jar_deps.copy()
      target.walk(lambda target: self._dependency_walk_work(undeclared_deps, undeclared_jar_deps, target))
      # The immediate (intransitive) missing deps are everything that isn't declared as a dep
      # of this target.
      immediate_missing_deps = computed_deps.difference(target.dependencies).difference([target])
      if len(undeclared_deps) > 0:
        found_missing_deps = True
        genmap = self.context.products.get('missing_deps')
        genmap.add(target, self.context._buildroot, [x.derived_from.address.reference() for x in undeclared_deps])
        for dep_target in undeclared_deps:
          print ("Error: target %s has undeclared compilation dependency on %s," %
                 (target.address, dep_target.derived_from.address.reference()))
          print ("       because source file %s depends on class %s" %
                 self.get_dependency_blame(target, dep_target))
          immediate_missing_deps.discard(dep_target)
      #if len(jar_deps) > 0:
      #  found_missing_deps = True
      #  for jd in jar_deps:
      #    print ("Error: target %s needs to depend on jar_dependency %s.%s" %
      #          (target.address, jd.org, jd.name))
      if self.check_intransitive_deps != "none":
        if len(immediate_missing_deps) > 0:
          genmap = self.context.products.get('missing_deps')
          if self.check_intransitive_deps == "error":
            found_missing_deps = True
            genmap.add(target, self.context._buildroot,
                       [x.derived_from.address.reference() for x in immediate_missing_deps])
          for missing in immediate_missing_deps:
            print ("Error: target %s depends on %s which is only declared transitively" % (target, missing))
      if self.check_unnecessary_deps:
        overdeps = target.declared_dependencies.difference(computed_deps)
        if len(overdeps) > 0:
          for d in overdeps:
            print ("Warning: target %s declares un-needed dependency on: %s" % (target, d))
    if found_missing_deps:
      raise TaskError('Missing dependencies detected.')

  def _dependency_walk_work(self, deps, jar_deps, target):
    if target in deps:
      deps.remove(target)
    if isinstance(target, JvmTarget):
      for jar_dep in target.dependencies:
        if jar_dep in jar_deps:
          jar_deps.remove(jar_dep)
