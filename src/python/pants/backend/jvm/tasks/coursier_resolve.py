# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import json
import logging
import os
import pickle
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
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class CoursierError(Exception):
  pass


class CoursierMixin(NailgunTask):

  @classmethod
  def implementation_version(cls):
    return super(CoursierMixin, cls).implementation_version() + [('CoursierMixin', 0)]

  @classmethod
  def register_options(cls, register):
    super(CoursierMixin, cls).register_options(register)

  @classmethod
  def subsystem_dependencies(cls):
    return super(CoursierMixin, cls).subsystem_dependencies() + (JarDependencyManagement, CoursierSubsystem)

  @staticmethod
  def _compute_jars_to_resolve_and_to_exclude(jars, artifact_set, manager):
    """

    :param jars_by_key:
    :param artifact_set:
    :param manager:
    :return:
    """

    if artifact_set is None:
      artifact_set = PinnedJarArtifactSet()

    jars_by_key = OrderedDict()
    for jar in jars:
      jars_for_the_key = jars_by_key.setdefault((jar.org, jar.name), [])
      jars_for_the_key.append(jar)

    jars_to_resolve = []
    exclude_args = set()

    untouched_pinned_artifact = set(M2Coordinate.create(x) for x in artifact_set)

    for k, jar_list in jars_by_key.items():
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

      jars_to_resolve.extend(jar_list)
      for jar in jar_list:
        for ex in jar.excludes:
          # `--` means exclude. See --soft-exclude-file in `coursier fetch --help`
          ex_arg = "{}:{}--{}:{}".format(jar.org, jar.name, ex.org, ex.name)
          exclude_args.add(ex_arg)

    return jars_to_resolve, exclude_args, untouched_pinned_artifact

  def cache_target_dirs(self):
    return True

  def resolve(self, targets, compile_classpath):
    """

    :param targets: a collection of targets to do 3rdparty resolve against
    :param compile_classpath: classpath product that holds the resolution result. IMPORTANT: this parameter will be changed.
    :return:
    """

    coursier_subsystem_instance = CoursierSubsystem.global_instance()

    coursier_jar = coursier_subsystem_instance.bootstrap_coursier()

    manager = JarDependencyManagement.global_instance()

    jar_targets = manager.targets_by_artifact_set(targets)

    for artifact_set, target_subset in jar_targets.items():
      # TODO(wisechengyi): this is the only place we are using IvyUtil method, which isn't specific to ivy really.
      raw_jar_deps, global_excludes = IvyUtils.calculate_classpath(target_subset)

      with self.invalidated(target_subset,
                            invalidate_dependents=False,
                            silent=False,
                            fingerprint_strategy=CouriserResolveFingerprintStrategy([])) as invalidation_check:

        target_resolution_filename = 'coursier_resolve.json'
        if not invalidation_check.invalid_vts:
          success = self._load_result_from_cache(compile_classpath, invalidation_check.all_vts,
                                               target_resolution_filename)
          if success:
            return

        jars_to_resolve, local_exclude_args, pinned_coords = self._compute_jars_to_resolve_and_to_exclude(raw_jar_deps,
                                                                                                          artifact_set,
                                                                                                          manager)
        # Prepare coursier args
        coursier_cache_path = os.path.join(self.get_options().pants_bootstrapdir, 'coursier')
        pants_jar_path_base = os.path.join(self.get_options().pants_workdir, 'coursier')
        safe_mkdir(pants_jar_path_base)

        coursier_workdir = os.path.join(self.get_options().pants_workdir, 'tmp')
        safe_mkdir(coursier_workdir)


        with temporary_file(coursier_workdir, cleanup=False) as f:
          output_fn = f.name

        common_args = ['fetch',
                       # Print the resolution tree
                       '-t',
                       '--cache', coursier_cache_path,
                       '--json-output-file', output_fn] + coursier_subsystem_instance.get_options().fetch_options

        def construct_classifier_to_jar(jars):
          product = defaultdict(list)
          for x in jars:
            product[x.coordinate.classifier or ''].append(x)
          return product

        classifier_to_jars = construct_classifier_to_jar(jars_to_resolve)

        # Coursier calls need to be divided by classifier because coursier treats classifier option globally.
        for classifier, classified_jars in classifier_to_jars.items():

          cmd_args = self._construct_cmd_args(classified_jars, classifier, common_args, global_excludes,
                                              local_exclude_args, pinned_coords, coursier_workdir)

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

              # return_code = subprocess.call(cmd_args,
              #                               stdout=workunit.output('stdout'),
              #                               stderr=workunit.output('stderr'))

              workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)

              if return_code:
                raise TaskError('The coursier process exited non-zero: {0}'.format(return_code))

              with open(output_fn) as f:
                result = json.loads(f.read())

          except subprocess.CalledProcessError as e:
            raise CoursierError(e)

          else:
            flattened_resolution = self._flatten_resolution_by_root(result)
            files_by_coord = self._map_coord_to_resolved_jars(result, coursier_cache_path, pants_jar_path_base)

            org_name_to_org_name_rev = {}
            for coord in files_by_coord.keys():
              (org, name, _) = coord.split(':')
              org_name_to_org_name_rev['{}:{}'.format(org, name)] = coord
            for vt in invalidation_check.all_vts:
              t = vt.target
            # for t in targets:
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
                  if simple_coord_candidate in files_by_coord:
                    final_simple_coord = simple_coord_candidate
                  elif simple_coord_candidate in result['conflict_resolution']:
                    final_simple_coord = result['conflict_resolution'][simple_coord_candidate]
                  # If still not found, look for org:name match.
                  else:
                    org_name = '{}:{}'.format(jar.org, jar.name)
                    if org_name in org_name_to_org_name_rev:
                      final_simple_coord = org_name_to_org_name_rev[org_name]

                  if final_simple_coord:
                    transitive_resolved_jars = get_transitive_resolved_jars(final_simple_coord, files_by_coord)
                    if transitive_resolved_jars:
                      compile_classpath.add_jars_for_targets([t], 'default' or classifier, transitive_resolved_jars)

        self._write_result_to_cache(compile_classpath, invalidation_check.all_vts, target_resolution_filename)

  def _write_result_to_cache(self, compile_classpath, all_vts, target_resolution_filename):
    # TODO(wisechengyi): currently the path contains abs path, so need to remove that before
    # cache can be shared across machines.
    for vt in all_vts:
      t = vt.target
      if isinstance(t, JarLibrary):
        with open(os.path.join(vt.results_dir, target_resolution_filename), 'w') as f:
          pickle.dump(compile_classpath.get_artifact_classpath_entries_for_targets([t]), f)
        vt.update()

  def _load_result_from_cache(self, compile_classpath, all_vts, target_resolution_filename):
    """

    :param compile_classpath:
    :param all_vts:
    :param target_resolution_filename:
    :return: True if success; False if any of the classpath is not valid anymore.
    """
    temp_store = []

    for vt in all_vts:
      t = vt.target
      if isinstance(t, JarLibrary):
        # compile_classpath.add_jars_for_targets
        with open(os.path.join(vt.results_dir, target_resolution_filename), 'r') as f:
          tuples_conf_artifact_classpath = pickle.load(f)
          for conf, artifact_classpath in tuples_conf_artifact_classpath:
            if not os.path.exists(artifact_classpath.path) \
                or not os.path.exists(artifact_classpath.cache_path) \
                or not os.path.exists(os.path.realpath(artifact_classpath.cache_path)):
              print("cache verification failed")
              return False
            temp_store.append((t, tuples_conf_artifact_classpath))

    # If all artifacts path are valid, add them to compile_classpath
    for t, tuples_conf_artifact_classpath in temp_store:
      compile_classpath.add_elements_for_target(t, tuples_conf_artifact_classpath)
    print("cache verified")
    return True

  def _construct_cmd_args(self, classified_jars, classifier, common_args, global_excludes, local_exclude_args,
                          pinned_coords, coursier_workdir):
    cmd_args = list(common_args)
    if classifier:
      cmd_args.extend(['--classifier', classifier])
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

    if local_exclude_args:

      with temporary_file(coursier_workdir, cleanup=False) as f:
        exclude_file = f.name
        with open(exclude_file, 'w') as ex_f:
          ex_f.write('\n'.join(local_exclude_args).encode('utf8'))

        cmd_args.append('--soft-exclude-file')
        cmd_args.append(exclude_file)

    # TODO(wisechengyi): support exclusion on the whole org
    for ex in global_excludes:
      if ex.org and ex.name:
        cmd_args.append('-E')
        cmd_args.append('{}:{}'.format(ex.org, ex.name))
    return cmd_args

  @classmethod
  def _flatten_resolution_by_root(cls, result):
    """
    Flatten the resolution by root dependencies. If we want to resolve X and Y, and X->A->B, and Y -> C,
    the result will be {X: [A, B], Y: [C]}

    :param result: see a nested dict capturing the resolution.
    :return: a flattened view with the top artifact as the roots.
    """

    def flat_walk(dep_map):
      for art in dep_map:
        for x in flat_walk(art['dependencies']):
          yield x
        yield art['coord']

    flat_result = defaultdict(list)

    for artifact in result['dependencies']:
      flat_result[artifact['coord']].extend(flat_walk(artifact['dependencies']))

    return flat_result

  @classmethod
  def _map_coord_to_resolved_jars(cls, result, coursier_cache_path, pants_jar_path_base):
    """
    Flatten the file paths corresponding to the coordinate from the nested json.

    :param result: coursier json output
    :param coursier_cache_path: coursier cache location
    :param pants_jar_path_base: location under pants workdir to store the symlink to the coursier cache
    :return: a map form simple coordinate to a set of resolved jars.
    """

    final_result = defaultdict(set)

    def walk(dep_map):
      for art in dep_map:

        for classifier, jar_path in art['files']:
          simple_coord = art['coord']
          coord = cls.to_m2_coord(simple_coord, classifier)
          pants_path = os.path.join(pants_jar_path_base, os.path.relpath(jar_path, coursier_cache_path))

          if not os.path.exists(pants_path):
            safe_mkdir(os.path.dirname(pants_path))
            os.symlink(jar_path, pants_path)

          resolved_jar = ResolvedJar(coord,
                                     cache_path=jar_path,
                                     pants_path=pants_path)
          final_result[simple_coord].add(resolved_jar)

        walk(art['dependencies'])

    walk(result['dependencies'])
    return final_result

  @classmethod
  def to_m2_coord(cls, coord_str, classifier=''):
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
    targets_by_sets = JarDependencyManagement.global_instance().targets_by_artifact_set(self.context.targets())
    for artifact_set, target_subset in targets_by_sets.items():
      self.resolve(target_subset, classpath_products)


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
