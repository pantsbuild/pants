# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import json
import os
import urllib
from collections import defaultdict

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.subsystems.jar_dependency_management import (JarDependencyManagement,
                                                                    PinnedJarArtifactSet)
from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.coursier.coursier_subsystem import CoursierSubsystem
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir


class CoursierResultNotFound(Exception):
  pass


class CoursierMixin(NailgunTask):
  """
  Experimental 3rdparty resolver using coursier.

  TODO(wisechengyi):
  1. Add relative url support
  """

  RESULT_FILENAME = 'result'

  @classmethod
  def subsystem_dependencies(cls):
    return super(CoursierMixin, cls).subsystem_dependencies() + (JarDependencyManagement, CoursierSubsystem)

  @classmethod
  def register_options(cls, register):
    super(CoursierMixin, cls).register_options(register)
    register('--allow-global-excludes', type=bool, advanced=False, fingerprint=True, default=True,
             help='Whether global excludes are allowed.')

  @staticmethod
  def _compute_jars_to_resolve_and_pin(raw_jars, artifact_set, manager):
    """
    This method provides settled lists of jar dependencies and coordinates
    based on conflict management.

    :param raw_jars: a collection of `JarDependencies`
    :param artifact_set: PinnedJarArtifactSet
    :param manager: JarDependencyManagement
    :return: (list of settled `JarDependency`, set of pinned `M2Coordinate`)
    """
    if artifact_set is None:
      artifact_set = PinnedJarArtifactSet()

    untouched_pinned_artifact = set(M2Coordinate.create(x) for x in artifact_set)
    jar_list = list(raw_jars)
    for i, dep in enumerate(jar_list):
      direct_coord = M2Coordinate.create(dep)
      # Portion to manage pinned jars in case of conflict
      if direct_coord in artifact_set:
        managed_coord = artifact_set[direct_coord]
        untouched_pinned_artifact.remove(managed_coord)

        if direct_coord.rev != managed_coord.rev:
          # It may be necessary to actually change the version number of the jar we want to resolve
          # here, because overrides do not apply directly (they are exclusively transitive). This is
          # actually a good thing, because it gives us more control over what happens.
          coord = manager.resolve_version_conflict(managed_coord, direct_coord, force=dep.force)

          # Once a version is settled, we force it anyway
          jar_list[i] = dep.copy(rev=coord.rev, force=True)

    return jar_list, untouched_pinned_artifact

  def resolve(self, targets, compile_classpath, sources, javadoc):
    """
    This is the core function for coursier resolve.

    Validation strategy:

    1. All targets are going through the `invalidated` to get fingerprinted in the target level.
       No cache is fetched at this stage because it is disabled.
    2. Once each target is fingerprinted, we combine them into a `VersionedTargetSet` where they
       are fingerprinted together, because each run of 3rdparty resolve is context sensitive.

    Artifacts are stored in `VersionedTargetSet`'s results_dir, the contents are the aggregation of
    each coursier run happened within that context.

    Caching: (TODO): https://github.com/pantsbuild/pants/issues/5187
    Currently it is disabled due to absolute paths in the coursier results.

    :param targets: a collection of targets to do 3rdparty resolve against
    :param compile_classpath: classpath product that holds the resolution result. IMPORTANT: this parameter will be changed.
    :param sources: if True, fetch sources for 3rdparty
    :param javadoc: if True, fetch javadoc for 3rdparty
    :return: n/a
    """

    manager = JarDependencyManagement.global_instance()

    jar_targets = manager.targets_by_artifact_set(targets)

    for artifact_set, target_subset in jar_targets.items():
      # TODO(wisechengyi): this is the only place we are using IvyUtil method, which isn't specific to ivy really.
      raw_jar_deps, global_excludes = IvyUtils.calculate_classpath(target_subset)

      # ['sources'] * False = [], ['sources'] * True = ['sources']
      confs_for_fingerprint = ['sources'] * sources + ['javadoc'] * javadoc
      fp_strategy = CoursierResolveFingerprintStrategy(confs_for_fingerprint)

      compile_classpath.add_excludes_for_targets(target_subset)

      with self.invalidated(target_subset,
                            invalidate_dependents=False,
                            silent=False,
                            fingerprint_strategy=fp_strategy) as invalidation_check:

        if not invalidation_check.all_vts:
          continue

        pants_workdir = self.get_options().pants_workdir
        resolve_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

        vt_set_results_dir = self._prepare_vts_results_dir(pants_workdir, resolve_vts)
        coursier_cache_dir, pants_jar_base_dir = self._prepare_workdir(pants_workdir)

        # Check each individual target without context first
        if not invalidation_check.invalid_vts:

          # If the individuals are valid, check them as a VersionedTargetSet
          if resolve_vts.valid:
            # Load up from the results dir
            success = self._load_from_results_dir(compile_classpath, vt_set_results_dir,
                                                  coursier_cache_dir, invalidation_check, pants_jar_base_dir)
            if success:
              return

        jars_to_resolve, pinned_coords = self._compute_jars_to_resolve_and_pin(raw_jar_deps,
                                                                               artifact_set,
                                                                               manager)

        results = self._get_result_from_coursier(jars_to_resolve, global_excludes, pinned_coords, pants_workdir,
                                                 coursier_cache_dir, sources, javadoc)

        for conf, result_list in results.items():
          for result in result_list:
            self._load_json_result(conf, compile_classpath, coursier_cache_dir, invalidation_check,
                                   pants_jar_base_dir, result)

        self._populate_results_dir(vt_set_results_dir, results)
        resolve_vts.update()

  def _prepare_vts_results_dir(self, pants_workdir, vts):
    """
    Given a `VergetTargetSet`, prepare its results dir.
    """
    vt_set_results_dir = os.path.join(pants_workdir, 'coursier', 'workdir', vts.cache_key.hash)
    safe_mkdir(vt_set_results_dir)
    return vt_set_results_dir

  def _prepare_workdir(self, pants_workdir):
    """
    Given pants workdir, prepare the location in pants workdir to store all the symlinks
    and coursier cache dir.
    """
    coursier_cache_dir = os.path.join(self.get_options().pants_bootstrapdir, 'coursier')
    pants_jar_base_dir = os.path.join(pants_workdir, 'coursier', 'cache')

    # Only pants_jar_path_base needs to be touched whereas coursier_cache_path will
    # be managed by coursier
    safe_mkdir(pants_jar_base_dir)
    return coursier_cache_dir, pants_jar_base_dir

  def _get_result_from_coursier(self, jars_to_resolve, global_excludes, pinned_coords, pants_workdir,
                                coursier_cache_path, sources, javadoc):
    """
    Calling coursier and return the result per invocation.

    If coursier was called once for classifier '' and once for classifier 'tests', then the return value
    would be: {'default': [<first coursier output>, <second coursier output>]}

    :param jars_to_resolve: List of `JarDependency`s to resolve
    :param global_excludes: List of `M2Coordinate`s to exclude globally
    :param pinned_coords: List of `M2Coordinate`s that need to be pinned.
    :param pants_workdir: Pants' workdir
    :param coursier_cache_path: path to where coursier cache is stored.

    :return: The aggregation of results by conf from coursier. Each coursier call could return
    the following:
        {
          "conflict_resolution": {
            "org:name:version" (requested): "org:name:version" (reconciled)
          },
          "dependencies": [
            {
              "coord": "orgA:nameA:versionA",
              "files": [
                [
                  <classifier>,
                  <path>,
                ]
              ],
              "dependencies": [ // coodinates for its transitive dependencies
                <orgX:nameX:versionX>,
                <orgY:nameY:versionY>,
              ]
            },
            {
              "coord": "orgB:nameB:versionB",
              "files": [
                [
                  <classifier>,
                  <path>,
                ]
              ],
              "dependencies": [ // coodinates for its transitive dependencies
                <orgX:nameX:versionX>,
                <orgZ:nameZ:versionZ>,
              ]
            },
            ... // more about orgX:nameX:versionX, orgY:nameY:versionY, orgZ:nameZ:versionZ
          ]
        }
    Hence the aggregation of the results will be in the following format, for example when default classifier
    and sources are fetched:
    {
      'default': [<result from coursier call with default conf with classifier X>,
                  <result from coursier call with default conf with classifier Y>],
      'src_doc': [<result from coursier call with --sources and/or --javadoc>],
    }
    """

    # Prepare coursier args
    coursier_subsystem_instance = CoursierSubsystem.global_instance()
    coursier_jar = coursier_subsystem_instance.bootstrap_coursier(self.context.new_workunit)

    common_args = ['fetch',
                   # Print the resolution tree
                   '-t',
                   '--cache', coursier_cache_path
                   ] + coursier_subsystem_instance.get_options().fetch_options

    coursier_work_temp_dir = os.path.join(pants_workdir, 'tmp')
    safe_mkdir(coursier_work_temp_dir)

    results_by_conf = self._get_default_conf_results(common_args, coursier_jar, global_excludes, jars_to_resolve,
                                                     coursier_work_temp_dir,
                                                     pinned_coords)
    if sources or javadoc:
      non_default_conf_results = self._get_non_default_conf_results(common_args, coursier_jar, global_excludes,
                                                                    jars_to_resolve, coursier_work_temp_dir,
                                                                    pinned_coords, sources, javadoc)
      results_by_conf.update(non_default_conf_results)

    return results_by_conf

  def _get_default_conf_results(self, common_args, coursier_jar, global_excludes, jars_to_resolve,
                                coursier_work_temp_dir,
                                pinned_coords):

    # Variable to store coursier result each run.
    results = defaultdict(list)
    with temporary_file(coursier_work_temp_dir, cleanup=False) as f:
      output_fn = f.name

    cmd_args = self._construct_cmd_args(jars_to_resolve,
                                        common_args,
                                        global_excludes if self.get_options().allow_global_excludes else [],
                                        pinned_coords,
                                        coursier_work_temp_dir,
                                        output_fn)

    results['default'].append(self._call_coursier(cmd_args, coursier_jar, output_fn))

    return results

  def _get_non_default_conf_results(self, common_args, coursier_jar, global_excludes, jars_to_resolve,
                                    coursier_work_temp_dir, pinned_coords,
                                    sources, javadoc):

    # To prevent improper api usage during development. User should not see this anyway.
    if not sources and not javadoc:
      raise TaskError("sources or javadoc has to be True.")

    with temporary_file(coursier_work_temp_dir, cleanup=False) as f:
      output_fn = f.name

    results = defaultdict(list)

    special_args = []
    if sources:
      special_args.append('--sources')

    if javadoc:
      special_args.append('--javadoc')

    cmd_args = self._construct_cmd_args(jars_to_resolve, common_args,
                                        global_excludes if self.get_options().allow_global_excludes else [],
                                        pinned_coords, coursier_work_temp_dir, output_fn)
    cmd_args.extend(special_args)

    # sources and/or javadoc share the same conf
    results['src_doc'] = [self._call_coursier(cmd_args, coursier_jar, output_fn)]
    return results

  def _call_coursier(self, cmd_args, coursier_jar, output_fn):

    with self.context.new_workunit(name='coursier', labels=[WorkUnitLabel.TOOL]) as workunit:
      return_code = self.runjava(
        classpath=[coursier_jar],
        main='coursier.cli.Coursier',
        args=cmd_args,
        jvm_options=self.get_options().jvm_options,
        # to let stdout/err through, but don't print tool's label.
        workunit_labels=[WorkUnitLabel.TOOL, WorkUnitLabel.SUPPRESS_LABEL])

      workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)

      if return_code:
        raise TaskError('The coursier process exited non-zero: {0}'.format(return_code))

      with open(output_fn) as f:
        return json.loads(f.read())

  @staticmethod
  def _construct_cmd_args(jars, common_args, global_excludes,
                          pinned_coords, coursier_workdir, json_output_path):

    # Make a copy, so there is no side effect or others using `common_args`
    cmd_args = list(common_args)

    cmd_args.extend(['--json-output-file', json_output_path])

    # Dealing with intransitivity and forced versions.
    for j in jars:
      if not j.rev:
        continue

      module = j.coordinate.simple_coord
      if j.coordinate.classifier:
        module += ',classifier={}'.format(j.coordinate.classifier)

      if j.get_url():
        jar_url = j.get_url()
        module += ',url={}'.format(urllib.quote_plus(jar_url))
        
      if j.intransitive:
        cmd_args.append('--intransitive')

      cmd_args.append(module)

      # Force requires specifying the coord again with -V
      if j.force:
        cmd_args.append('-V')
        cmd_args.append(j.coordinate.simple_coord)

    # Force pinned coordinates
    for m2coord in pinned_coords:
      cmd_args.append('-V')
      cmd_args.append(m2coord.simple_coord)

    # Local exclusions
    local_exclude_args = []
    for jar in jars:
      for ex in jar.excludes:
        # `--` means exclude. See --local-exclude-file in `coursier fetch --help`
        # If ex.name does not exist, that means the whole org needs to be excluded.
        ex_arg = "{}:{}--{}:{}".format(jar.org, jar.name, ex.org, ex.name or '*')
        local_exclude_args.append(ex_arg)

    if local_exclude_args:
      with temporary_file(coursier_workdir, cleanup=False) as f:
        exclude_file = f.name
        with open(exclude_file, 'w') as ex_f:
          ex_f.write('\n'.join(local_exclude_args).encode('utf8'))

        cmd_args.append('--local-exclude-file')
        cmd_args.append(exclude_file)

    for ex in global_excludes:
      cmd_args.append('-E')
      cmd_args.append('{}:{}'.format(ex.org, ex.name or '*'))

    return cmd_args

  def _load_json_result(self, conf, compile_classpath, coursier_cache_path, invalidation_check,
                        pants_jar_path_base, result):
    """
    Given a coursier run result, load it into compile_classpath by target.

    :param compile_classpath: `ClasspathProducts` that will be modified
    :param coursier_cache_path: cache location that is managed by coursier
    :param invalidation_check: InvalidationCheck
    :param pants_jar_path_base: location under pants workdir that contains all the symlinks to coursier cache
    :param result: result dict converted from the json produced by one coursier run
    :return: n/a
    """
    # Parse the coursier result
    flattened_resolution = self._extract_dependencies_by_root(result)
    coord_to_resolved_jars = self._map_coord_to_resolved_jars(result, coursier_cache_path, pants_jar_path_base)

    # Construct a map from org:name to reconciled org:name:version
    org_name_to_org_name_rev = {}
    for coord in coord_to_resolved_jars.keys():
      (org, name, _) = coord.split(':')
      org_name_to_org_name_rev['{}:{}'.format(org, name)] = coord

    for vt in invalidation_check.all_vts:
      t = vt.target
      if isinstance(t, JarLibrary):
        def get_transitive_resolved_jars(my_simple_coord, classifier, resolved_jars):
          transitive_jar_path_for_coord = []
          if my_simple_coord in flattened_resolution:
            # TODO(wisechengyi): this only grabs jar with matching classifier the current coordinate
            # and it still takes the jars wholesale for its transitive dependencies.
            # https://github.com/coursier/coursier/issues/743
            resolved_jars_with_matching_classifier = filter(
              lambda x: x.coordinate.classifier == classifier or x.coordinate.classifier in ['sources', 'javadoc'],
              resolved_jars[my_simple_coord])

            transitive_jar_path_for_coord.extend(resolved_jars_with_matching_classifier)

            for c in flattened_resolution[my_simple_coord]:
              transitive_jar_path_for_coord.extend(resolved_jars[c])

          return transitive_jar_path_for_coord

        for jar in t.jar_dependencies:
          simple_coord_candidate = jar.coordinate.simple_coord
          final_simple_coord = None
          if simple_coord_candidate in coord_to_resolved_jars:
            final_simple_coord = simple_coord_candidate
          elif simple_coord_candidate in result['conflict_resolution']:
            final_simple_coord = result['conflict_resolution'][simple_coord_candidate]
          # If still not found, look for org:name match.
          else:
            org_name = '{}:{}'.format(jar.org, jar.name)
            if org_name in org_name_to_org_name_rev:
              final_simple_coord = org_name_to_org_name_rev[org_name]

          if final_simple_coord:
            transitive_resolved_jars = get_transitive_resolved_jars(final_simple_coord, jar.coordinate.classifier, coord_to_resolved_jars)
            if transitive_resolved_jars:
              compile_classpath.add_jars_for_targets([t], conf, transitive_resolved_jars)

  def _populate_results_dir(self, vts_results_dir, results):

    with open(os.path.join(vts_results_dir, self.RESULT_FILENAME), 'w') as f:
      json.dump(results, f)

  def _load_from_results_dir(self, compile_classpath, vts_results_dir,
                             coursier_cache_path, invalidation_check, pants_jar_path_base):
    """
    Given vts_results_dir, load the results which can be from multiple runs of coursier into compile_classpath.

    :return: True if success; False if any of the classpath is not valid anymore.
    """
    result_file_path = os.path.join(vts_results_dir, self.RESULT_FILENAME)
    if not os.path.exists(result_file_path):
      return

    with open(result_file_path, 'r') as f:
      results = json.load(f)
      for conf, result_list in results.items():
        for result in result_list:
          try:
            self._load_json_result(conf, compile_classpath,
                                   coursier_cache_path,
                                   invalidation_check,
                                   pants_jar_path_base, result)
          except CoursierResultNotFound:
            return False

    return True

  @classmethod
  def _extract_dependencies_by_root(cls, result):
    """
    Only extracts the transitive dependencies for the given coursier resolve.
    Note the "dependencies" field is already transitive.

    Example:
    {
      "conflict_resolution": {},
      "dependencies": [
        {
          "coord": "a",
          "dependencies": ["b", "c"]
          "files": ...
        },
        {
          "coord": "b",
          "dependencies": []
          "files": ...
        },
        {
          "coord": "c",
          "dependencies": []
          "files": ...
        }
      ]
    }

    Should return { "a": ["b", "c"], "b": [], "c": [] }

    :param result: coursier result like the example.
    :return: a simplified view with the top artifact as the roots.
    """
    flat_result = defaultdict(list)

    for artifact in result['dependencies']:
      flat_result[artifact['coord']].extend(artifact['dependencies'])

    return flat_result

  @classmethod
  def _map_coord_to_resolved_jars(cls, result, coursier_cache_path, pants_jar_path_base):
    """
    Map resolved files to each org:name:version

    Example:
    {
      "conflict_resolution": {},
      "dependencies": [
        {
          "coord": "a",
          "dependencies": ["b", "c"],
          "files": [ ["", "a.jar"], ["sources", "a-sources.jar"] ]
        },
        {
          "coord": "b",
          "dependencies": [],
          "files": [ ["", "b.jar"] ]
        },
        {
          "coord": "c",
          "dependencies": [],
          "files": [ ["", "c.jar"] ]
        }
      ]
    }

    Should return:
    {
      "a": { ResolvedJar(classifier='', path/cache_path="a.jar"),
             ResolvedJar(classifier='sources', path/cache_path="a-sources.jar") },
      "b": { ResolvedJar(classifier='', path/cache_path="b.jar") },
      "c": { ResolvedJar(classifier='', path/cache_path="c.jar") },
    }

    :param result: coursier json output
    :param coursier_cache_path: coursier cache location
    :param pants_jar_path_base: location under pants workdir to store the symlink to the coursier cache
    :return: a map from org:name:version to a set of resolved jars.
    """

    coord_to_resolved_jars = defaultdict(set)

    for dep in result['dependencies']:

      for classifier, jar_path in dep['files']:
        simple_coord = dep['coord']
        coord = cls.to_m2_coord(simple_coord, classifier)
        pants_path = cls._get_path_to_jar(coursier_cache_path, pants_jar_path_base, jar_path)
      
        if not os.path.exists(jar_path):
          raise CoursierResultNotFound("Jar path not found: {}".format(jar_path))

        if not os.path.exists(pants_path):
          safe_mkdir(os.path.dirname(pants_path))
          os.symlink(jar_path, pants_path)

        resolved_jar = ResolvedJar(coord,
                                   cache_path=jar_path,
                                   pants_path=pants_path)
        coord_to_resolved_jars[simple_coord].add(resolved_jar)

    return coord_to_resolved_jars

  @classmethod
  def _get_path_to_jar(cls, coursier_cache_path, pants_jar_path_base, jar_path):
    """
    Create the path to the jar that will live in .pants.d
    
    :param coursier_cache_path: coursier cache location
    :param pants_jar_path_base: location under pants workdir to store the symlink to the coursier cache
    :param jar_path: path of the jar
    :return:
    """
    if os.path.abspath(coursier_cache_path) not in os.path.abspath(jar_path):
      # Appending the string 'absolute' to the jar_path and joining that is a hack to work around
      # python's os.path.join behavior of throwing away all components that come before an
      # absolute path. See https://docs.python.org/3.3/library/os.path.html#os.path.join
      return os.path.join(pants_jar_path_base, os.path.normpath('absolute/' + jar_path))
    else:
      return os.path.join(pants_jar_path_base, 'relative', os.path.relpath(jar_path, coursier_cache_path))

  @classmethod
  def to_m2_coord(cls, coord_str, classifier):
    # TODO: currently assuming all packaging is a jar
    return M2Coordinate.from_string(coord_str + ':{}:jar'.format(classifier))


class CoursierResolve(CoursierMixin):

  @classmethod
  def subsystem_dependencies(cls):
    return super(CoursierResolve, cls).subsystem_dependencies() + (JvmResolveSubsystem,)

  @classmethod
  def product_types(cls):
    return ['compile_classpath']

  @classmethod
  def prepare(cls, options, round_manager):
    super(CoursierResolve, cls).prepare(options, round_manager)
    round_manager.require_data('java')
    round_manager.require_data('scala')

  @classmethod
  def register_options(cls, register):
    super(CoursierResolve, cls).register_options(register)

  @classmethod
  def implementation_version(cls):
    return super(CoursierResolve, cls).implementation_version() + [('CoursierResolve', 1)]
  
  def execute(self):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """

    jvm_resolve_subsystem = JvmResolveSubsystem.global_instance()
    if jvm_resolve_subsystem.get_options().resolver != 'coursier':
      return

    # executor = self.create_java_executor()
    classpath_products = self.context.products.get_data('compile_classpath',
                                                        init_func=ClasspathProducts.init_func(
                                                          self.get_options().pants_workdir))

    self.resolve(self.context.targets(), classpath_products, sources=False, javadoc=False)

  def check_artifact_cache_for(self, invalidation_check):
    # Coursier resolution is an output dependent on the entire target set, and is not divisible
    # by target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]


class CoursierResolveFingerprintStrategy(FingerprintStrategy):

  def __init__(self, confs):
    super(CoursierResolveFingerprintStrategy, self).__init__()
    self._confs = sorted(confs or [])

  def compute_fingerprint(self, target):
    hash_elements_for_target = []
    if isinstance(target, JarLibrary):
      managed_jar_artifact_set = JarDependencyManagement.global_instance().for_target(target)
      if managed_jar_artifact_set:
        hash_elements_for_target.append(str(managed_jar_artifact_set.id))

      hash_elements_for_target.append(target.payload.fingerprint())
    elif isinstance(target, JvmTarget) and target.payload.excludes:
      hash_elements_for_target.append(target.payload.fingerprint(field_keys=('excludes',)))
    else:
      pass

    if not hash_elements_for_target:
      return None

    hasher = hashlib.sha1()
    hasher.update(target.payload.fingerprint())

    for conf in self._confs:
      hasher.update(conf)

    for element in hash_elements_for_target:
      hasher.update(element)

    # Just in case so we do not collide with ivy cache
    hasher.update('coursier')

    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), '-'.join(self._confs)))

  def __eq__(self, other):
    return type(self) == type(other) and self._confs == other._confs
