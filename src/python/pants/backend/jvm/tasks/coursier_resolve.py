# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import json
import logging
import os
from collections import defaultdict

from twitter.common.collections import OrderedDict

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
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class CoursierError(Exception):
  pass


class CouriserCacheNotFound(Exception):
  pass


class CoursierMixin(NailgunTask):

  RESULT_FILENAME = 'result'

  @classmethod
  def subsystem_dependencies(cls):
    return super(CoursierMixin, cls).subsystem_dependencies() + (JarDependencyManagement, CoursierSubsystem)

  @staticmethod
  def _compute_jars_to_resolve_and_pin(raw_jars, artifact_set, manager):
    """

    :param raw_jars: a collection of `JarDependencies`
    :param artifact_set:
    :param manager:
    :return: (list of settled `JarDependency`, set of pinned `M2Coordinate`)
    """
    if artifact_set is None:
      artifact_set = PinnedJarArtifactSet()

    jars_by_key = OrderedDict()
    for jar in raw_jars:
      # (wisechengyi) This is equivalent to OrderedDefaultDict
      jars_for_the_key = jars_by_key.setdefault((jar.org, jar.name), [])
      jars_for_the_key.append(jar)

    jars_to_resolve = []

    untouched_pinned_artifact = set(M2Coordinate.create(x) for x in artifact_set)

    for k, jar_list in jars_by_key.items():

      # Portion to managed pinned jars in case of conflict
      for i, dep in enumerate(jar_list):
        direct_coord = M2Coordinate.create(dep)

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

      # Once the jar list is settled, add it to the global list later passed to coursier
      jars_to_resolve.extend(jar_list)

    return jars_to_resolve, untouched_pinned_artifact

  def resolve(self, targets, compile_classpath):
    """
    This is the core function for coursier resolve.

    Validation strategy:

    1. All targets are going through the `invalidated` to get fingerprinted in the target level.
       No cache is fetched at stage.
    2. Once each target is fingerprinted, we combine them into a `VersionedTargetSet` where they
       are fingerprinted together, because each run of 3rdparty resolve is context sensitive.

    Artifacts are stored in `VersionedTargetSet`'s results_dir, the content are the aggregation of each

    Caching: (TODO): https://github.com/pantsbuild/pants/issues/5187
    Currently it is disabled due to absolute paths in the coursier results.

    :param targets: a collection of targets to do 3rdparty resolve against
    :param compile_classpath: classpath product that holds the resolution result. IMPORTANT: this parameter will be changed.
    :return: n/a
    """

    manager = JarDependencyManagement.global_instance()

    jar_targets = manager.targets_by_artifact_set(targets)

    for artifact_set, target_subset in jar_targets.items():
      # TODO(wisechengyi): this is the only place we are using IvyUtil method, which isn't specific to ivy really.
      raw_jar_deps, global_excludes = IvyUtils.calculate_classpath(target_subset)

      with self.invalidated(target_subset,
                            invalidate_dependents=False,
                            silent=False,
                            fingerprint_strategy=CouriserResolveFingerprintStrategy([])) as invalidation_check:

        if not invalidation_check.all_vts:
          continue

        pants_workdir = self.get_options().pants_workdir
        resolve_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

        vt_set_results_dir = os.path.join(pants_workdir, 'coursier', 'workdir', resolve_vts.cache_key.hash)
        safe_mkdir(vt_set_results_dir)

        coursier_cache_path = os.path.join(self.get_options().pants_bootstrapdir, 'coursier')
        pants_jar_path_base = os.path.join(pants_workdir, 'coursier', 'cache')
        safe_mkdir(pants_jar_path_base)

        # Check each individual target without context first
        if not invalidation_check.invalid_vts:

          # If the individuals are valid, check them as a VersionedTargetSet
          if resolve_vts.valid:
            # Load up from the results dir
            success = self._load_from_results_dir(compile_classpath, vt_set_results_dir,
                                                  coursier_cache_path, invalidation_check, pants_jar_path_base)
            if success:
              return

        jars_to_resolve, pinned_coords = self._compute_jars_to_resolve_and_pin(raw_jar_deps,
                                                                               artifact_set,
                                                                               manager)

        results = self._get_result_from_coursier(global_excludes,
                                                 jars_to_resolve, pants_workdir,
                                                 pinned_coords, coursier_cache_path)

        for classifier, result in results.items():
          self._load_json_result(classifier, compile_classpath, coursier_cache_path, invalidation_check,
                                 pants_jar_path_base, result)

        self._populate_results_dir(vt_set_results_dir, results)
        resolve_vts.update()

  def _get_result_from_coursier(self, global_excludes, jars_to_resolve,
                                pants_workdir, pinned_coords, coursier_cache_path):
    """
    Calling coursier and return the result per invocation.

    If coursier was called once for classifier '' and once for classifier 'tests', then the return value
    would be: {'': <first couriser output>, 'tests': <second coursier output>}

    :param global_excludes:
    :param jars_to_resolve:
    :param local_exclude_args:
    :param pants_workdir:
    :param pinned_coords:
    :param coursier_cache_path:
    :return:
    """

    # Prepare coursier args
    coursier_subsystem_instance = CoursierSubsystem.global_instance()
    coursier_jar = coursier_subsystem_instance.bootstrap_coursier()

    coursier_workdir = os.path.join(pants_workdir, 'tmp')
    safe_mkdir(coursier_workdir)
    with temporary_file(coursier_workdir, cleanup=False) as f:
      output_fn = f.name
    common_args = ['fetch',
                   # Print the resolution tree
                   '-t',
                   '--cache', coursier_cache_path,
                   '--json-output-file', output_fn] + coursier_subsystem_instance.get_options().fetch_options

    def construct_classifier_to_jar(jars):
      """
      Reshape jars by classifier

      For example:
      [
        ResolvedJar('sources', 'a-sources.jar'),
        ResolvedJar('sources', 'b-sources.jar'),
        ResolvedJar('', 'a.jar'),
      ]
      should yield:
      {
        'sources': [ResolvedJar('sources', 'a-sources.jar'),ResolvedJar('sources', 'b-sources.jar')],
        '':  [ResolvedJar('', 'a.jar') ]
      }
      """
      product = defaultdict(list)
      for x in jars:
        product[x.coordinate.classifier or ''].append(x)
      return product

    classifier_to_jars = construct_classifier_to_jar(jars_to_resolve)
    # Divide the resolve by classifier because coursier treats classifier option globally.

    results = {}

    for classifier, classified_jars in classifier_to_jars.items():

      cmd_args = self._construct_cmd_args(classified_jars, classifier, common_args, global_excludes,
                                          pinned_coords, coursier_workdir)

      cmd_str = ' '.join(cmd_args)
      logger.info(cmd_str)

      try:
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
            result = json.loads(f.read())
            results[classifier] = result

      except subprocess.CalledProcessError as e:
        raise CoursierError(e)

    return results

  @staticmethod
  def _construct_cmd_args(classified_jars, classifier, common_args, global_excludes,
                          pinned_coords, coursier_workdir):
    cmd_args = list(common_args)

    # Append classifier if not default
    if classifier != '':
      cmd_args.extend(['--classifier', classifier])

    # Dealing with intransitivity and forced versions.
    for j in classified_jars:
      if not j.rev:
        continue

      if j.intransitive:
        cmd_args.append('--intransitive')

      cmd_args.append(j.coordinate.simple_coord)

      # Force requires specifying the coord again with -V
      if j.force:
        cmd_args.append('-V')
        cmd_args.append(j.coordinate.simple_coord)

    # Force pinned coordinates
    for j in pinned_coords:
      cmd_args.append('-V')
      cmd_args.append(j.simple_coord)

    # Local exclusions
    local_exclude_args = []
    for jar in classified_jars:
      for ex in jar.excludes:
        # `--` means exclude. See --soft-exclude-file in `coursier fetch --help`
        # If ex.name does not exist, that means the whole org needs to be excluded.
        ex_arg = "{}:{}--{}:{}".format(jar.org, jar.name, ex.org, ex.name or '*')
        local_exclude_args.append(ex_arg)

    if local_exclude_args:
      with temporary_file(coursier_workdir, cleanup=False) as f:
        exclude_file = f.name
        with open(exclude_file, 'w') as ex_f:
          ex_f.write('\n'.join(local_exclude_args).encode('utf8'))

        cmd_args.append('--soft-exclude-file')
        cmd_args.append(exclude_file)

    for ex in global_excludes:
      cmd_args.append('-E')
      cmd_args.append('{}:{}'.format(ex.org, ex.name or '*'))

    return cmd_args

  def _load_json_result(self, classifier, compile_classpath, coursier_cache_path, invalidation_check,
                        pants_jar_path_base, result):
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
        def get_transitive_resolved_jars(my_simple_coord, resolved_jars):
          transitive_jar_path_for_coord = []
          if my_simple_coord in flattened_resolution:
            for c in [my_simple_coord] + flattened_resolution[my_simple_coord]:
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
            transitive_resolved_jars = get_transitive_resolved_jars(final_simple_coord, coord_to_resolved_jars)
            if transitive_resolved_jars:
              compile_classpath.add_jars_for_targets([t], 'default' or classifier, transitive_resolved_jars)

  def _populate_results_dir(self, vts_results_dir, results):
    # TODO(wisechengyi): currently the path contains abs path, so need to remove that before
    # cache can be shared across machines.

    with open(os.path.join(vts_results_dir, self.RESULT_FILENAME), 'w') as f:
      json.dump(results, f)

  def _load_from_results_dir(self, compile_classpath, vts_results_dir,
                             coursier_cache_path, invalidation_check, pants_jar_path_base):
    """

    :return: True if success; False if any of the classpath is not valid anymore.
    """
    result_file_path = os.path.join(vts_results_dir, self.RESULT_FILENAME)
    if not os.path.exists(result_file_path):
      return

    with open(result_file_path, 'r') as f:
      results = json.load(f)
      for classifier, result in results.items():
        try:
          self._load_json_result(classifier, compile_classpath,
                                 coursier_cache_path,
                                 invalidation_check,
                                 pants_jar_path_base, result)
        except CouriserCacheNotFound:
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
        pants_path = os.path.join(pants_jar_path_base, os.path.relpath(jar_path, coursier_cache_path))

        if not os.path.exists(jar_path):
          raise CouriserCacheNotFound("Jar path not found: {}".format(jar_path))

        if not os.path.exists(pants_path):
          safe_mkdir(os.path.dirname(pants_path))
          os.symlink(jar_path, pants_path)

        resolved_jar = ResolvedJar(coord,
                                   cache_path=jar_path,
                                   pants_path=pants_path)
        coord_to_resolved_jars[simple_coord].add(resolved_jar)

    return coord_to_resolved_jars

  @classmethod
  def to_m2_coord(cls, coord_str, classifier):
    # TODO: currently assuming all packaging is a jar
    return M2Coordinate.from_string(coord_str + ':{}:jar'.format(classifier))


class CoursierResolve(CoursierMixin):
  """
  Experimental 3rdparty resolver using coursier.

  # TODO(wisechengyi):
  # 1. Add conf support
  # 2. Add relative url support
  """

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

    # confs = ['default']
    self.resolve(self.context.targets(), classpath_products)


class CouriserResolveFingerprintStrategy(FingerprintStrategy):

  def __init__(self, confs):
    super(CouriserResolveFingerprintStrategy, self).__init__()
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
