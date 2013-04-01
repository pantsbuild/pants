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

from twitter.pants.base.target import Target
from twitter.pants.targets.jar_dependency import JarDependency
from twitter.pants.targets.jvm_target import JvmTarget
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.scala.zinc_analysis_file import ZincAnalysisCollection


class JvmDependencyCache(object):
  """ Class which computes compilation dependencies of targets for jvm-based languages.

  The behavior of this is determined by flags set in the compilation task's context.
  The flags (set by command-line options) are:
  - check_missing_deps: the master flag, which determines whether the dependency checks should
     be run at all.
  - check_intransitive_deps: a flag which determines whether or not to generate errors about
    intransitive dependency errors, where a target has a dependency on another target which
    it doesn't declare, but which is part of its transitive dependency graph. If this is set
    to "none", intransitive errors won't be reported. If "warn", then it will print warning
    messages, but will not cause the build to fail, and will not populate build products with 
    the errors. If "error", then the messages will be printed, build products populated, and 
    the build will fail.
  - check_unnecessary_deps: if set to True, then warning messages will be printed about 
    dependencies that are declared, but not actually required.
  """

  @staticmethod
  def init_product_requirements(task):
    """ Set the compilation product requirements that are needed for dependency analysis.

    Parameters:
      task: the task whose products should be set.
    """
    task._computed_jar_products = False
    task.context.products.require('classes')
    task.context.products.require("ivy_jar_products")

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    """ Set up command-line options for dependency checking.

    Any jvm compilation task that wants to use dependency analysis can call this from
    its setup_parser method to add the appropriate options for dependency testing.

    See scala_compile.py for an example.
    """
    option_group.add_option(mkflag("check-missing-deps"), mkflag("check-missing-deps", 
                                                                 negate=True),
                            dest="scala_check_missing_deps",
                            action="callback", callback=mkflag.set_bool,
                            default=True,
                            help="[%default] Check for undeclared dependencies in scala code")

    # This flag should eventually be removed once code is in compliance.
    option_group.add_option(mkflag("check-missing-intransitive-deps"),
                            type="choice",
                            action='store',
                            dest='scala_check_intransitive_deps',
                            choices=['none', 'warn', 'error'],
                            default='none',
                            help="[%default] Enable errors for undeclared deps that don't " \
                              "cause compilation errors, because the dependencies are " \
                              "provided transitively.")
    option_group.add_option(mkflag("check-unnecessary-deps"),
                            mkflag("check-unnecessary-deps", negate=True),
                            dest='scala_check_unnecessary_deps',
                            action="callback", callback=mkflag.set_bool,
                            default=False,
                            help="[%default] Enable warnings for declared dependencies " \
                              "that are not needed.")

  def __init__(self, context, targets, all_analysis_files):
    """
    Parameters:
      context: The task context instance.
      targets: The set of targets to analyze. These should all be target types that
               inherit from jvm_target, and contain source files that will be compiled into
               jvm class files.
      all_analysis_files: The analysis files of the targets to analyze, and all their deps.
    """

    # The package prefixes are part of a hack to make it possible to use the
    # zinc caches for dependency analysis. We need to be able to convert from
    # a class file path and the name of the class contained in the file, without
    # expending the cost of reading every class file to find its name.
    # The package prefixes are the names of the root packages - typically
    # "com", "org", "net".
    self.package_prefixes = context.config.getlist('scala-compile', 
                                                   'dep-analysis-package-prefixes')
    if self.package_prefixes is None:
      self.package_prefixes = [ 'com', 'org', 'net', 'scala' ]
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

    # Maps between targets and the source files that are provided by those targets.
    self.targets_by_source = None
    self.sources_by_target = None   

    # Maps between targets and the classes that are provided by those targets.
    self.targets_by_class = None
    self.classes_by_target = None

    # Map from targets to the binary dependencies of that target.
    self.binary_deps_by_target = None
    # map from targets to the source dependencies of that target.
    self.source_deps_by_target = None

    # Map from targets to the class dependencies of that target.
    self.class_deps_by_target = None

    self.computed_deps = None

  def _get_jardep_dependencies(self, target):
    """ Gets the transitive closure of the the set of declared jar dependencies. """
    result = []
    target.walk(lambda t: self._walk_jardeps(t, result))
    return set(result)

  def _walk_jardeps(self, target, result):
    """A dependency walker for extracting jar dependencies"""
    if isinstance(target, JarDependency):
      result.append(target)
    if isinstance(target, JvmTarget):
      result.extend(target.jar_dependencies)

  def _compute_jardep_contents(self):
    """ Compute the relations between jar dependencies and jar files.

    Returns: a pair of maps, (jars_by_target, targets_by_jar) describing the mappings between 
       jars and the targets that contain those jars.
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
    """ Normalize a source file relative to the target that provides it.

    Given a target and a source file path specified by that target, produce a normalized
    path for the source file that matches the pathname used in the zinc analysis files.
    """
    return os.path.join(target.target_base, src)

  def get_analysis_collection(self):
    """ Populates and retrieves the merged analysis collection for this compilation """

    if self.zinc_analysis_collection is None:
      self.zinc_analysis_collection = \
          ZincAnalysisCollection(False,
                                 package_prefixes=self.package_prefixes)
      for af in self.all_analysis_files:
        basedir = os.path.relpath(af.class_basedir, self.context._buildroot)
        self.zinc_analysis_collection.add_and_parse_file(af.analysis_file, basedir)
    return self.zinc_analysis_collection

  def get_targets_by_class(self):
    """ Memoizing getter for a map from classes to the targets that provide them. """
    if self.targets_by_class is None:
      self._compute_classfile_dependency_relations()
    return self.targets_by_class

  def get_binary_deps_by_target(self):
    """ Memoizing getter for a map from targets to their binary dependencies. """
    if self.binary_deps_by_target is None:
      self._compute_classfile_dependency_relations()
    return self.binary_deps_by_target
      
  def _compute_classfile_dependency_relations(self):
    """ Compute the dependency relations based on binary and classname deps.

    Walks through the zinc analysis relations that are expressed in terms of
    dependencies on class files, and translate class file references to class
    references.

    This is an internal implementation which populates instance variables that
    store cached analysis results. It updates two values:

     - targets_by_class is a map from product classes to the targets that provided them, and
     - binary_deps_by_target is a map from targets to the classes that zinc reported they
       have a binary dependency on.
    """    
    zinc_analysis = self.get_analysis_collection()
    targets_by_class = defaultdict(set)
    binary_deps_by_target = defaultdict(set)
    # Set up the map from products to the targets that provide them,
    # and from targets to the classes they depend on.
    for target in self.targets:
      for src in target.sources:
        srcpath = self._normalize_source_path(target, src)
        # the classes produced by a target can be specified in zinc relations by 
        # an entry in the products, or an entry in the classes, or both. Where it appears
        # depends on the specifics of the last compilation call.
        for product in zinc_analysis.product_classes[srcpath]:
          targets_by_class[product].add(target)
        for classname in zinc_analysis.class_names[srcpath]:
          targets_by_class[classname].add(target)
        for bindep in zinc_analysis.binary_dep_classes[srcpath]:
          binary_deps_by_target[target].add(bindep)
    self.targets_by_class = targets_by_class
    self.binary_deps_by_target = binary_deps_by_target

  def get_sources_by_target(self):
    """ Memoizing getter for a map from targets to the sources provided by those targets. """
    if self.sources_by_target is None:
      self._compute_source_relations()
    return self.sources_by_target

  def get_targets_by_source(self):
    """ Memoizing getter for a map from sources to the targets that provide those sources. """
    if self.targets_by_source is None:
      self._compute_source_relations()
    return self.targets_by_source

  def _compute_source_relations(self):
    """ Compute the targets_by_source and sources_by_target maps. """
    self.sources_by_target = defaultdict(set)
    self.targets_by_source = defaultdict(set)
    for target in self.targets:
      for src in target.sources:
        srcpath = self._normalize_source_path(target, src)
        self.sources_by_target[target].add(srcpath)
        self.targets_by_source[srcpath].add(target)
    return (self.sources_by_target, self.targets_by_source)

  def _check_overlapping_sources(self, targets_by_source):
    """ Detect overlapping targets where if a source file is included in more than one target """
    overlapping_sources = set()
    for s in targets_by_source:
      if len(targets_by_source[s]) > 1:
        overlapping_sources.add(s)
        print "Error: source file %s included in multiple targets %s" % (s, targets_by_source[s])
    
  def get_computed_jar_dependency_relations(self):
    """  Compute maps from target to the jars that the target provides """
    # Figure out which jars are in which targets, and then use with the zinc
    (self.ivy_jars_by_target, self.ivy_targets_by_jar) = self._compute_jardep_contents()
    computed_jar_deps = defaultdict(set)
    for target in self.targets:
      for src in target.sources:
        srcpath = self._normalize_source_path(target, src)
        jardeps = self.zinc_analysis_collection.binary_deps[srcpath]
        for j in jardeps:
          computed_jar_deps[target] |= self.ivy_targets_by_jar[j]
    return computed_jar_deps

  def get_compilation_dependencies(self, sources_by_target, targets_by_source,
                                   targets_by_product, binary_deps_by_target):
    """ Compute a map from the source files in a target to class files that it depends on

    Note: this code currently relies on the relations report generated by the zinc incremental
    scala compiler. If other languages/compilers want to use this code, they need to provide
    a similar report. See zinc_analysis_file.py for details about the information
    needed by this analysis.

    Parameters:
      sources_by_target: a map from targets to the source file that they provide.
      targets_by_source: a map from source files to the targets that provide them.
      targets_by_product: a map from classes to the targets that provide them.
      binary_deps_by_target: a map from targets to the classes that they depend on.
    Returns: a target-to-target mapping from targets to targets that they depend on.
       If this was already computed, return the already computed result.
    """

    zinc_analysis = self.get_analysis_collection()

    # Use data about targets to convert the zinc cache stuff into target -> target pendencies.
    targets_by_source = self.get_targets_by_source()
    sources_by_target = self.get_sources_by_target()
    targets_by_class = self.get_targets_by_class()
    binary_deps_by_target = self.get_binary_deps_by_target()
    self.source_deps_by_target = defaultdict(set)

    self._check_overlapping_sources(targets_by_source)

    # map from targets to the classes that they depend on.
    self.class_deps_by_target = defaultdict(set)

    # Then generate a map from targets to the classes that they depend on.
    for target in self.targets:
      if target in binary_deps_by_target:
        self.class_deps_by_target[target] |= binary_deps_by_target[target]
      for src in target.sources:
        srcpath = self._normalize_source_path(target, src)
        self.class_deps_by_target[target] |= zinc_analysis.external_deps[srcpath]
        for srcdep in zinc_analysis.source_deps[srcpath]:
          self.source_deps_by_target[target] |= self.targets_by_source[srcdep]
        if srcpath in zinc_analysis.class_names:
          self.class_deps_by_target[target] |= zinc_analysis.class_names[srcpath]

    self.computed_deps = defaultdict(set)
    for fromtarget in self.class_deps_by_target:
      for classdep in self.class_deps_by_target[fromtarget]:
        if classdep in targets_by_class:
          self.computed_deps[fromtarget] |= targets_by_class[classdep]
    for fromtarget in self.source_deps_by_target:
      for totarget in self.source_deps_by_target[fromtarget]:
        self.computed_deps[fromtarget].add(totarget)
          
    
    # Figure out which jars are in which targets, and then use with the zinc
    # binary dependencies to figure out which jars belong to which targets.

    self.computed_jar_deps = self.get_computed_jar_dependency_relations()

    return self.computed_deps, self.computed_jar_deps

  def get_dependency_blame(self, from_target, to_target, targets_by_class, targets_by_source):
    """ Figures out why target A depends on target B according the the dependency analysis.

    Generates a tuple which can be used to generate a message like:
     "*from_target* depends on *to_target* because *from_target*'s source file X
      depends on *to_target*'s class Y."

    Params:
      from_target: the target which has a missing dependency.
      to_target: the target that from_target has an undeclared dependency on.
      targets_by_class: a map from classes to the targets that provide them.
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
      for cl in self.get_analysis_collection().external_deps[srcpath]:
        targets_providing = targets_by_class[cl]
        if to_target in targets_providing:
          return source, cl
      for depsrc in self.get_analysis_collection().source_deps[srcpath]:
        if to_target in targets_by_source[depsrc]:
          return source, depsrc
    return None, None

  def get_missing_deps_for_target(self, target, computed_deps, computed_jar_deps,
                                  targets_by_class, targets_by_source):
    """  Compute the missing dependencies for a specific target.

    Parameters:
      target: the target
      computed_deps: the computed dependencies for the target.
      computed_jar_deps: the computed jar dependencies for the target.
      targets_by_class: a mapping specifying which classes are produced by which targets.

    Return:
      (undeclared_deps, intransitive_undeclared_deps)
    """
    # Make copies of the computed deps. Then we'll walk the declared deps,
    # removing everything that was declared; what's left are the undeclared deps.
    undeclared_deps = computed_deps.copy()
    undeclared_jar_deps = computed_jar_deps.copy()
    target.walk(lambda target: \
      self._dependency_walk_work(undeclared_deps, undeclared_jar_deps, target))
    # The intransitive missing deps are everything that isn't declared as a dep
    # of this target.
    intransitive_undeclared_deps = \
        computed_deps.difference(target.dependencies).difference([target])
    if not target.has_label("synthetic") and len(undeclared_deps) > 0:
      genmap = self.context.products.get('missing_deps')
      genmap.add(target, self.context._buildroot,
                 [ x.derived_from.address.reference() for x in undeclared_deps])
      for dep_target in undeclared_deps:
        print ("Error: target %s has undeclared compilation dependency on %s," %
               (target.address, dep_target.derived_from.address.reference()))
        print ("       because source file %s depends on class %s" %
               self.get_dependency_blame(target, dep_target, targets_by_class, targets_by_source))
        intransitive_undeclared_deps.discard(dep_target)
    if self.check_intransitive_deps is not 'none' and len(intransitive_undeclared_deps) > 0:
      genmap = self.context.products.get('missing_intransitive_deps')
      genmap.add(target, self.context._buildroot, \
        [ x.derived_from.address.reference() for x in intransitive_undeclared_deps])
      for dep_target in intransitive_undeclared_deps:
        print ("Error: target %s has undeclared intransitive compilation dependency on %s," %
               (target.address, dep_target.derived_from.address.reference()))
        print ("       because source file %s depends on class %s" %
               self.get_dependency_blame(target, dep_target, targets_by_class, targets_by_source))

    return undeclared_deps, intransitive_undeclared_deps


  def check_undeclared_dependencies(self):
    """ Performs the undeclared dependencies/overdeclared dependencies checks.

    For each dependency issue discovered, generates warnings/error messages and
    (depending on flag settings), setting build products.
    """
    if not self.check_missing_deps:
        return
    sources_by_target = self.get_sources_by_target()
    targets_by_source = self.get_targets_by_source()
    targets_by_class = self.get_targets_by_class()
    binary_deps_by_target = self.get_binary_deps_by_target()

    (deps_by_target, jar_deps_by_target) = \
        self.get_compilation_dependencies(sources_by_target, targets_by_source,
                                          targets_by_class, binary_deps_by_target)
    found_missing_deps = False
    for target in deps_by_target:
      computed_deps = deps_by_target[target]
      computed_jar_deps = jar_deps_by_target[target]
      undeclared_deps, immediate_undeclared_deps = \
        self.get_missing_deps_for_target(target, computed_deps, computed_jar_deps,
                                         targets_by_class, targets_by_source)

      #if len(jar_deps) > 0:
      #  found_missing_deps = True
      #  for jd in jar_deps:
      #    print ("Error: target %s needs to depend on jar_dependency %s.%s" %
      #          (target.address, jd.org, jd.name))

      if self.check_unnecessary_deps:
        if not target.has_label('synthetic'):
          self.check_target_unnecessary_deps(target, computed_deps)

    if found_missing_deps:
      raise TaskError('Missing dependencies detected.')

  def check_target_unnecessary_deps(self, target, computed_deps):
    """ Generate warning messages about unnecessary declared dependencies.

    Params:
      target: the target to be checked for undeclared dependencies
      computed_deps: the actual dependencies computed for that target.
    """
    # Sometimes if there was an error, the processed_dependencies for a target will be 
    # None; if so, we need to skip that target.
    if target.processed_dependencies is not None:
      declared_deps = \
          [ t for t in target.processed_dependencies if hasattr(t, "address") ]
      overdeps = set(declared_deps).difference(computed_deps)
      if len(overdeps) > 0:
        for deptarget in overdeps:
          if isinstance(deptarget, JvmTarget) and not deptarget.has_label('synthetic'):
            print ("Warning: target %s declares un-needed dependency on: %s" % 
                   (target, deptarget))


  def _dependency_walk_work(self, deps, jar_deps, target):
    if target in deps:
      deps.remove(target)
    if isinstance(target, JvmTarget):
      for jar_dep in target.dependencies:
        if jar_dep in jar_deps:
          jar_deps.remove(jar_dep)


