# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import logging
import os
import threading
from collections import OrderedDict, defaultdict
from hashlib import sha1

from twitter.common.collections import OrderedSet

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.task.task import TaskBase
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir
from pants.util.memo import memoized_property


_FETCH_RESOLVE_IVY_XML_FILE_NAME = 'fetch-ivy.xml'

_FULL_RESOLVE_IVY_XML_FILE_NAME = 'ivy.xml'

_RESOLVE_FILE_NAME = 'resolution.json'

logger = logging.getLogger(__name__)


class FrozenResolution(object):
  def __init__(self):
    self.target_to_resolved_coordinates = defaultdict(OrderedSet)
    self.all_resolved_coordinates = OrderedSet()

  def add_resolved_jars(self, target, resolved_jars):
    coords = [j.coordinate for j in resolved_jars]
    self.add_resolution_coords(target, coords)

  def add_resolution_coords(self, target, coords):
    for c in coords:
      self.target_to_resolved_coordinates[target].add(c)
      self.all_resolved_coordinates.add(c)

  def target_spec_to_coordinate_strings(self):
    return {t.address.spec: [str(c) for c in coordinates]
            for t, coordinates in self.target_to_resolved_coordinates.items()}

  def all_coordinate_strings(self):
    return [str(c) for c in self.all_resolved_coordinates]

  def __repr__(self):
    return 'FrozenResolution(\n  target_to_resolved_coordinates\n    {}\n  all\n    {}'.format(
      '\n    '.join(':  '.join([t.address.spec,
                                '\n      '.join(str(c) for c in cs)])
                    for t,cs in self.target_to_resolved_coordinates.items()),
      '\n    '.join(str(c) for c in self.all_resolved_coordinates)
    )

  def __eq__(self, other):
    return (type(self) == type(other) and
            self.all_resolved_coordinates == other.all_resolved_coordinates and
            self.target_to_resolved_coordinates == other.target_to_resolved_coordinates)

  def __ne__(self, other):
    return not self == other

  @classmethod
  def load_from_file(cls, filename, targets):
    if not os.path.exists(filename):
      return None

    with open(filename) as f:
      # Using OrderedDict here to maintain insertion order of dict entries.
      from_file = json.load(f, object_pairs_hook=OrderedDict)
    result = {}
    target_lookup = {t.address.spec: t for t in targets}
    for conf, serialized_resolution in from_file.items():
      resolution = FrozenResolution()
      for spec, coord_strs in serialized_resolution['target_to_coords'].items():
        t = target_lookup[spec] # TODO error handling
        resolution.add_resolution_coords(t, [M2Coordinate.from_string(c) for c in coord_strs])
      resolution.all_resolved_coordinates = OrderedSet(M2Coordinate.from_string(c) for c in serialized_resolution['coords'])
      result[conf] = resolution
    return result

  @classmethod
  def dump_to_file(cls, filename, resolutions_by_conf):
    res = {}
    for conf, resolution in resolutions_by_conf.items():
      res[conf] = OrderedDict([
        ['target_to_coords',resolution.target_spec_to_coordinate_strings()],
        ['coords', resolution.all_coordinate_strings()]
      ])
    with safe_concurrent_creation(filename) as tmp_filename:
      with open(tmp_filename, 'wb') as f:
        json.dump(res, f)


class IvyFullResolveResult(object):
  """A class wrapping the classpath, a mapping from ivy cache jars to their linked location
     under .pants.d, and the id of the reports associated with the resolve."""

  def __init__(self, classpath, symlink_map, resolve_hash_name):
    self.classpath = classpath
    self.resolve_hash_name = resolve_hash_name
    self._symlink_map = symlink_map

  @property
  def completed_resolve(self):
    return self.resolve_hash_name is not None

  def ivy_info_for(self, ivy_cache_dir, conf):
    return IvyUtils.parse_xml_report(ivy_cache_dir, self.resolve_hash_name, conf)

  def collect_resolved_jars(self, ivy_cache_dir, conf, targets):
    """Finds the resolved jars for each jar_library target in targets and yields them with the
    target.

    :param ivy_cache_dir:
    :param conf:
    :param targets:
    :yield: target, resolved_jars
    :raises IvyTaskMixin.UnresolvedJarError
    """
    ivy_info = self.ivy_info_for(ivy_cache_dir, conf)
    if not ivy_info:
      return

    jar_library_targets = [t for t in targets if isinstance(t, JarLibrary)]
    ivy_jar_memo = {}
    for target in jar_library_targets:
      # Add the artifacts from each dependency module.
      resolved_jars = self._resolved_jars_blah(conf, ivy_info, ivy_jar_memo,
                                               target.jar_dependencies, target)
      yield target, resolved_jars

  def _new_resolved_jar_with_symlink_path(self, conf, tgt, resolved_jar_without_symlink):
    def candidate_cache_paths():
      # There is a focus on being lazy here to avoid `os.path.realpath` when we can.
      yield resolved_jar_without_symlink.cache_path
      yield os.path.realpath(resolved_jar_without_symlink.cache_path)

    for cache_path in candidate_cache_paths():
      pants_path = self._symlink_map.get(cache_path)
      if pants_path:
        break
    else:
      raise IvyTaskMixin.UnresolvedJarError(
        'Jar {resolved_jar} in {spec} not resolved to the ivy '
        'symlink map in conf {conf}.'
        .format(spec=tgt.address.spec,
                resolved_jar=resolved_jar_without_symlink.cache_path,
                conf=conf))

    return ResolvedJar(coordinate=resolved_jar_without_symlink.coordinate,
                       pants_path=pants_path,
                       cache_path=resolved_jar_without_symlink.cache_path)

  def _resolved_jars_blah(self, conf, ivy_info, ivy_jar_memo, resolved_coordinates, target):
    raw_resolved_jars = ivy_info.get_resolved_jars_for_coordinates(resolved_coordinates,
                                                                   memo=ivy_jar_memo)
    resolved_jars = [self._new_resolved_jar_with_symlink_path(conf, target, raw_resolved_jar)
                     for raw_resolved_jar in raw_resolved_jars]
    return resolved_jars


class IvyFetchResolveResult(IvyFullResolveResult):
  def __init__(self, classpath, symlink_map, resolve_hash_name, frozen_resolutions):
    super(IvyFetchResolveResult, self).__init__(classpath, symlink_map,
                                                            resolve_hash_name)
    self._frozen_resolutions = frozen_resolutions

  def collect_resolved_jars(self, ivy_cache_dir, conf, targets):
    """Finds the resolved jars for each jar_library target in targets and yields them with the
    target.

    Overrides to handle the specific case of fetch.

    :param ivy_cache_dir:
    :param conf:
    :param targets:
    :yield: target, resolved_jars
    :raises IvyTaskMixin.UnresolvedJarError
    """
    ivy_info = self.ivy_info_for(ivy_cache_dir, conf)
    if not ivy_info:
      return

    jar_library_targets = [t for t in targets if isinstance(t, JarLibrary)]
    ivy_jar_memo = {}
    for target in jar_library_targets:
      #resolved_jars = self._add_artifacts_for_each_module(conf, ivy_info, ivy_jar_memo, target)
      resolved_coordinates = self._coordinates_for_target_in_resolve(conf, target)
      # TODO validate versions
      resolved_jars =self._resolved_jars_blah(conf, ivy_info, ivy_jar_memo, resolved_coordinates, target)

      yield target, resolved_jars

  def _coordinates_for_target_in_resolve(self, conf, target):
    return self._frozen_resolutions[conf].target_to_resolved_coordinates.get(target)


_NO_TARGETS_RESULT = IvyFullResolveResult([], {}, None)


class IvyResolveFingerprintStrategy(FingerprintStrategy):

  def __init__(self, confs):
    super(IvyResolveFingerprintStrategy, self).__init__()
    self._confs = sorted(confs or [])

  def compute_fingerprint(self, target):

    hash_elements_for_target = []

    if isinstance(target, JarLibrary):
      managed_jar_dependencies_artifacts = JarDependencyManagement.global_instance().for_target(target)
      if managed_jar_dependencies_artifacts:
        hash_elements_for_target.append(str(managed_jar_dependencies_artifacts.id))

      hash_elements_for_target.append(target.payload.fingerprint())
    elif isinstance(target, JvmTarget) and target.payload.excludes:
      hash_elements_for_target.append(target.payload.fingerprint(field_keys=('excludes',)))
    else:
      pass

    if not hash_elements_for_target:
      return None

    hasher = sha1()
    for conf in self._confs:
      hasher.update(conf)

    for element in hash_elements_for_target:
      hasher.update(element)

    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), '-'.join(self._confs)))

  def __eq__(self, other):
    return type(self) == type(other) and self._confs == other._confs


class IvyTaskMixin(TaskBase):
  """A mixin for Tasks that execute resolves via Ivy.

  NB: Ivy reports are not relocatable in a cache, and a report must be present in order to
  parse the graph structure of dependencies. Therefore, this mixin explicitly disables the
  cache for its invalidation checks via the `use_cache=False` parameter. Tasks that extend
  the mixin may safely enable task-level caching settings.
  """

  class Error(TaskError):
    """Indicates an error performing an ivy resolve."""

  class UnresolvedJarError(Error):
    """Indicates a jar dependency couldn't be mapped."""

  @classmethod
  def global_subsystems(cls):
    return super(IvyTaskMixin, cls).global_subsystems() + (IvySubsystem, JarDependencyManagement)

  @classmethod
  def register_options(cls, register):
    super(IvyTaskMixin, cls).register_options(register)
    register('--jvm-options', action='append', metavar='<option>...',
             help='Run Ivy with these extra jvm options.')
    register('--soft-excludes', action='store_true', default=False, advanced=True,
             help='If a target depends on a jar that is excluded by another target '
                  'resolve this jar anyway')

  # Protect writes to the global map of jar path -> symlinks to that jar.
  symlink_map_lock = threading.Lock()

  @classmethod
  def implementation_version(cls):
    return super(IvyTaskMixin, cls).implementation_version() + [('IvyTaskMixin', 1)]

  @memoized_property
  def ivy_cache_dir(self):
    """The path of the ivy cache dir used for resolves.

    :rtype: string
    """
    # TODO(John Sirois): Fixup the IvySubsystem to encapsulate its properties.
    return IvySubsystem.global_instance().get_options().cache_dir

  def _collect_existing_reports(self, confs, resolve_hash_name):
    report_missing = False
    report_paths = []
    for conf in confs:
      report_path = IvyUtils.xml_report_path(self.ivy_cache_dir, resolve_hash_name, conf)
      if not os.path.exists(report_path):
        report_missing = True
        break
      else:
        report_paths.append(report_path)
    return report_missing, report_paths

  def resolve(self, executor, targets, classpath_products, confs=None, extra_args=None,
              invalidate_dependents=False):
    """Resolves external classpath products (typically jars) for the given targets.

    :param executor: A java executor to run ivy with.
    :type executor: :class:`pants.java.executor.Executor`
    :param targets: The targets to resolve jvm dependencies for.
    :type targets: :class:`collections.Iterable` of :class:`pants.build_graph.target.Target`
    :param classpath_products: The classpath products to populate with the results of the resolve.
    :type classpath_products: :class:`pants.backend.jvm.tasks.classpath_products.ClasspathProducts`
    :param confs: The ivy configurations to resolve; ('default',) by default.
    :type confs: :class:`collections.Iterable` of string
    :param extra_args: Any extra command line arguments to pass to ivy.
    :type extra_args: list of string
    :param bool invalidate_dependents: `True` to invalidate dependents of targets that needed to be
                                        resolved.
    :returns: The id of the reports associated with this resolve.
    :rtype: string
    """
    confs = confs or ('default',)
    targets_by_sets = JarDependencyManagement.global_instance().targets_by_artifact_set(targets)
    resolve_hash_names = []
    for artifact_set, target_subset in targets_by_sets.items():
      resolve_hash_names.append(self._resolve_subset(executor,
                                                     target_subset,
                                                     classpath_products,
                                                     confs=confs,
                                                     extra_args=extra_args,
                                                     invalidate_dependents=invalidate_dependents,
                                                     pinned_artifacts=artifact_set))
    return resolve_hash_names

  def ivy_classpath(self, targets, silent=True, workunit_name=None):
    """Create the classpath for the passed targets.
    :param targets: A collection of targets to resolve a classpath for.
    :type targets: collection.Iterable
    """
    result = self._ivy_resolve(targets, silent=silent, workunit_name=workunit_name)
    return result.classpath

  def _resolve_subset(self, executor, targets, classpath_products, confs=None, extra_args=None,
              invalidate_dependents=False, pinned_artifacts=None):
    result = self._ivy_resolve(
      targets,
      executor=executor,
      workunit_name='ivy-resolve',
      confs=confs,
      extra_args=extra_args,
      invalidate_dependents=invalidate_dependents,
      pinned_artifacts=pinned_artifacts,
    )

    if not result.completed_resolve:
      # There was no resolve to do, so no 3rdparty deps to process below.
      return

    # After running ivy, we parse the resulting reports, and record the dependencies for
    # all relevant targets (ie: those that have direct dependencies).
    # Record the ordered subset of jars that each jar_library/leaf depends on using
    # stable symlinks within the working copy.
    classpath_products.add_excludes_for_targets(targets)
    for conf in confs:
      for target, resolved_jars in result.collect_resolved_jars(self.ivy_cache_dir,
                                                                conf, targets):
        classpath_products.add_jars_for_targets([target], conf, resolved_jars)

    return result.resolve_hash_name

  def _ivy_resolve(self,
                  targets,
                  executor=None,
                  silent=False,
                  workunit_name=None,
                  confs=None,
                  extra_args=None,
                  invalidate_dependents=False,
                  pinned_artifacts=None):
    """Resolves external dependencies for the given targets.

    If there are no targets suitable for jvm transitive dependency resolution, an empty result is
    returned, ie: ([], {}, None).

    :param targets: The targets to resolve jvm dependencies for.
    :type targets: :class:`collections.Iterable` of :class:`pants.build_graph.target.Target`
    :param executor: A java executor to run ivy with.
    :type executor: :class:`pants.java.executor.Executor`

    :param confs: The ivy configurations to resolve; ('default',) by default.
    :type confs: :class:`collections.Iterable` of string
    :param extra_args: Any extra command line arguments to pass to ivy.
    :type extra_args: list of string
    :param bool invalidate_dependents: `True` to invalidate dependents of targets that needed to be
                                        resolved.
    :returns: The result of the resolve.
    :rtype: IvyFullResolveResult
    """
    # If there are no targets, we don't need to do a resolve.
    if not targets:
      return _NO_TARGETS_RESULT

    confs = confs or ('default',)
    extra_args = extra_args or []

    fingerprint_strategy = IvyResolveFingerprintStrategy(confs)

    with self.invalidated(targets,
                          invalidate_dependents=invalidate_dependents,
                          silent=silent,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:
      # In case all the targets were filtered out because they didn't participate in fingerprinting.
      if not invalidation_check.all_vts:
        return _NO_TARGETS_RESULT

      resolve_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

      resolve_hash_name = resolve_vts.cache_key.hash

      ivy_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir, 'ivy')
      resolve_workdir = os.path.join(ivy_workdir, resolve_hash_name)

      symlink_classpath_filename = os.path.join(resolve_workdir, 'classpath')
      ivy_cache_classpath_filename = symlink_classpath_filename + '.raw'

      safe_mkdir(resolve_workdir)

      def last_resolve_was_full_resolve():
        # If there is a full resolve ivy.xml, then we have done a full resolve.
        # TODO need additional / better constraints though.
        # TODO eg
        # TODO ivy.xml exists, but a rm -rf ~/.ivy2 has happened.
        return os.path.exists(os.path.join(resolve_workdir, _FULL_RESOLVE_IVY_XML_FILE_NAME))

      def last_resolve_was_fetch_resolve():
        # if there is a fetch resolve ivy.xml, then we have done a fetch resolve.
        # TODO need additional / better constraints though.
        # TODO eg
        # TODO ivy.xml exists, but a rm -rf ~/.ivy2 has happened.
        return os.path.exists(os.path.join(resolve_workdir, _FETCH_RESOLVE_IVY_XML_FILE_NAME))

      def has_frozen_resolve():
        # If the only file in the resolve workdir is the resolution file,
        # then it most likely came from cache. There's probably other expressions
        # we could use to double check though.
        only_cached_resolve_file = [_RESOLVE_FILE_NAME] == os.listdir(resolve_workdir)
        return only_cached_resolve_file

      # Resolution loading code, fast paths followed by slow paths.
      # Fast paths
      # 1. if last was successful fetch resolve, (req valid)
      # 2. if last was successful full resolve   (req valid)
      # Slow paths
      # 1. if last was loaded from cache         (req valid)
      # 2. invalid do a slow full resolve

      if last_resolve_was_fetch_resolve():
        ## load fetch ##
        # prereqs: fetch-report, resolve.json
        # TODO reorg ala below w/ tests checking validity
        # load resolve.json
        # load report
        # if invalid
        #   clear non-cache workdir and start over
        potential_frozen_resolutions = self._load_frozen_resolutions(resolve_workdir, targets)
        return self._load_from_fetch_resolve(
          ivy_cache_classpath_filename,
          symlink_classpath_filename,
          ivy_workdir,
          resolve_hash_name,
          potential_frozen_resolutions)

      if last_resolve_was_full_resolve():
        ## load full ##
        # TODO reorg ala below w/ tests checking validity
        # load report
        # if invalid
        #   clear non-cache workdir and start over
        # if no resolve.json, complain or drop and cache
        return self._load_from_full_resolve(
          ivy_cache_classpath_filename,
          symlink_classpath_filename, ivy_workdir,
          resolve_hash_name)

      if has_frozen_resolve():
        ## fetch resolve bits ##
        # TODO reorg ala below w/ tests checking validity
        # load resolve.json
        # do resolve
        # mv report to non-cache workdir
        # ret result
        potential_frozen_resolutions = self._load_frozen_resolutions(resolve_workdir, targets)
        self._do_fetch_resolve(confs, executor, extra_args,
                               ivy_cache_classpath_filename,
                               potential_frozen_resolutions, resolve_hash_name, resolve_vts,
                               resolve_workdir, workunit_name)
        result = self._load_from_fetch_resolve(
          ivy_cache_classpath_filename,
          symlink_classpath_filename, ivy_workdir,
          resolve_hash_name,
          potential_frozen_resolutions#
        )
        return result

      if invalidation_check.invalid_vts:
        # NB: Invalid here means that there was no matching fingerprint, so there can't be one of the above.
        # pre-reqs: local workdir copy was invalidated, and no cached resolve.
        ## full resolve bits ##
        # TODO reorg ala below w/ tests checking validity
        # do resolve
        # mv report to non-cache workdir
        # drop & cache resolve.json
        # ret result
        return self._do_full_resolve_cache_and_load(confs, executor, extra_args,
                                                    ivy_cache_classpath_filename,
                                                    symlink_classpath_filename,
                                                    ivy_workdir, pinned_artifacts,
                                                    resolve_hash_name,
                                                    resolve_vts, resolve_workdir, targets,
                                                    workunit_name)

      # Weird base case: no valid fetch resolve, no valid full resolve, no cached frozen resolve and
      # it wasn't invalid, so no full resolve. But, there were no errors trying to do the above
      # either.
      #
      # Undefined as yet. It may be that we'd want to do a full resolve in this case
      # We might also want to blow up with information about what happened, and a possible fix.
      raise Exception('something')

  def _do_full_resolve_cache_and_load(self, confs, executor, extra_args,
                                ivy_cache_classpath_filename,
                                symlink_classpath_filename,
                                ivy_workdir, pinned_artifacts, resolve_hash_name, resolve_vts,
                                resolve_workdir, targets, workunit_name):
    self._do_full_resolve(confs, executor, extra_args, resolve_vts, pinned_artifacts,
                          ivy_cache_classpath_filename,
                          resolve_hash_name, resolve_workdir, workunit_name)
    result = self._load_from_full_resolve(
      ivy_cache_classpath_filename,
      symlink_classpath_filename, ivy_workdir,
      resolve_hash_name)

    self._construct_and_cache_frozen_resolutions(confs, resolve_vts, resolve_workdir, result,
                                                 targets)
    return result

  def _construct_and_cache_frozen_resolutions(self, confs, resolve_vts, resolve_workdir, result,
                                              targets):
    frozen_resolutions_by_conf = self.construct_frozen_resolutions_by_conf(confs, result, targets)
    self.dump_frozen_resolutions(resolve_workdir, frozen_resolutions_by_conf)
    if self.artifact_cache_writes_enabled():
      self.update_artifact_cache([(resolve_vts, [self._frozen_resolve_file(resolve_workdir)])])

  def _load_from_fetch_resolve(self, ivy_cache_classpath_filename,
                               symlink_classpath_filename,
                               ivy_workdir, resolve_hash_name, frozen_resolutions):
    symlink_map = self._symlink_from_cache_path(self.ivy_cache_dir, ivy_workdir,
                                                ivy_cache_classpath_filename,
                                                symlink_classpath_filename)
    classpath = IvyUtils.load_classpath_from_cachepath(
      symlink_classpath_filename)
    result = IvyFetchResolveResult(classpath, symlink_map, resolve_hash_name, frozen_resolutions=frozen_resolutions)
    return result

  def _load_from_full_resolve(self, ivy_cache_classpath_filename,
                               symlink_classpath_filename,
                               ivy_workdir, resolve_hash_name):
    result = self._symlink_stuff_and_construct_resolve_result(ivy_workdir, resolve_hash_name,
                                                              ivy_cache_classpath_filename,
                                                              symlink_classpath_filename)
    return result

  def _do_fetch_resolve(self, confs, executor, extra_args,
                        ivy_cache_classpath_filename,
                        potential_frozen_resolution, resolve_hash_name, resolve_vts,
                        resolve_workdir, workunit_name):
    self._run_fetch_resolve(confs,
                            executor,
                            extra_args,
                            resolve_vts,
                            ivy_cache_classpath_filename,
                            resolve_hash_name,
                            resolve_workdir,
                            workunit_name + '-fetch',
                            potential_frozen_resolution)

  def _symlink_stuff_and_construct_resolve_result(self, ivy_workdir, resolve_hash_name, ivy_cache_classpath_filename,
                                                symlink_classpath_filename):
    symlink_map = self._symlink_from_cache_path(self.ivy_cache_dir, ivy_workdir,
                                                ivy_cache_classpath_filename,
                                                symlink_classpath_filename)
    classpath = IvyUtils.load_classpath_from_cachepath(
      symlink_classpath_filename)
    result = IvyFullResolveResult(classpath, symlink_map, resolve_hash_name)
    return result

  def construct_frozen_resolutions_by_conf(self, confs, result, targets):
    frozen_resolutions_by_conf = OrderedDict()
    for conf in confs:
      frozen_resolution = FrozenResolution()
      for target, resolved_jars in result.collect_resolved_jars(self.ivy_cache_dir, conf, targets):
        frozen_resolution.add_resolved_jars(target, resolved_jars)
      frozen_resolutions_by_conf[conf] = frozen_resolution
    return frozen_resolutions_by_conf

  def dump_frozen_resolutions(self, resolve_workdir, resolutions_by_conf):
    filename = self._frozen_resolve_file(resolve_workdir)
    FrozenResolution.dump_to_file(filename, resolutions_by_conf)

  def _frozen_resolve_file(self, resolve_workdir):
    return os.path.join(resolve_workdir, _RESOLVE_FILE_NAME)

  def load_frozen_resolutions(self, resolve_workdir, targets):
    # returns a dict of conf -> FrozenResolution
    filename = self._frozen_resolve_file(resolve_workdir)
    return FrozenResolution.load_from_file(filename, targets)

  def _do_full_resolve(self, confs, executor, extra_args, global_vts, pinned_artifacts,
                       raw_target_classpath_file, resolve_hash_name, resolve_workdir,
                       workunit_name):
    ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=self.context.new_workunit)
    with safe_concurrent_creation(raw_target_classpath_file) as raw_target_classpath_file_tmp:
      args = ['-cachepath', raw_target_classpath_file_tmp] + extra_args

      targets=global_vts.targets
      use_soft_excludes=self.get_options().soft_excludes
      # TODO(John Sirois): merge the code below into IvyUtils or up here; either way, better
      # diagnostics can be had in `IvyUtils.generate_ivy` if this is done.
      # See: https://github.com/pantsbuild/pants/issues/2239
      jars, global_excludes = IvyUtils.calculate_classpath(targets)

      # Don't pass global excludes to ivy when using soft excludes.
      if use_soft_excludes:
        global_excludes = []

      ivyxml = os.path.join(resolve_workdir, _FULL_RESOLVE_IVY_XML_FILE_NAME)
      with IvyUtils.ivy_lock:
        try:
          IvyUtils.generate_ivy(targets, jars, global_excludes, ivyxml, confs,
                                resolve_hash_name, pinned_artifacts)
        except IvyUtils.IvyError as e:
          raise self.Error('Failed to prepare ivy resolve: {}'.format(e))

        try:
          IvyUtils.exec_ivy(ivy, confs, ivyxml, args,
                            jvm_options=self.get_options().jvm_options,
                            executor=executor,
                            workunit_name=workunit_name,
                            workunit_factory=self.context.new_workunit)
        except IvyUtils.IvyError as e:
          raise self.Error('Ivy resolve failed: {}'.format(e))

      self.validate_classpath_file_creation(raw_target_classpath_file_tmp)
    logger.debug('Moved ivy classfile file to {dest}'.format(dest=raw_target_classpath_file))

  def validate_classpath_file_creation(self, raw_target_classpath_file_tmp):
    if not os.path.exists(raw_target_classpath_file_tmp):
      raise self.Error('Ivy failed to create classpath file at {}'
                       .format(raw_target_classpath_file_tmp))

  def _run_fetch_resolve(self, confs, executor, extra_args, global_vts,
                          raw_target_classpath_file, resolve_hash_name, resolve_workdir,
                          workunit_name, frozen_resolutions):
    # resolve resolutions has all the bits in it to do a boring fetch resolve.
    # poc
    #
    ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=self.context.new_workunit)
    with safe_concurrent_creation(raw_target_classpath_file) as raw_target_classpath_file_tmp:
      args = ['-cachepath', raw_target_classpath_file_tmp] + extra_args
      targets=global_vts.targets,

      ivyxml = os.path.join(resolve_workdir, _FETCH_RESOLVE_IVY_XML_FILE_NAME)
      with IvyUtils.ivy_lock:
        try:
          # so we have all the jars with their versions in resolve_stuffs, so we don't need to do anything
          # maybe some validation though
          # TODO validate , and use more than just default.
          jars = frozen_resolutions.get('default').all_resolved_coordinates
          IvyUtils.generate_fetch_ivy(targets, ivyxml, confs, resolve_hash_name, jars)
        except IvyUtils.IvyError as e:
          raise self.Error('Failed to prepare ivy resolve: {}'.format(e))

        try:
          IvyUtils.exec_ivy(ivy, confs, ivyxml, args,
                            jvm_options=self.get_options().jvm_options,
                            executor=executor,
                            workunit_name=workunit_name,
                            workunit_factory=self.context.new_workunit)
        except IvyUtils.IvyError as e:
          raise self.Error('Ivy resolve failed: {}'.format(e))

      self.validate_classpath_file_creation(raw_target_classpath_file_tmp)
    logger.debug('Moved ivy classfile file to {dest}'.format(dest=raw_target_classpath_file))

  def _symlink_from_cache_path(self, ivy_cache_dir, ivy_workdir, raw_target_classpath_file,
                               target_classpath_file):
    # Make our actual classpath be symlinks, so that the paths are uniform across systems.
    # Note that we must do this even if we read the raw_target_classpath_file from the artifact
    # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
    with IvyTaskMixin.symlink_map_lock:
      # A common dir for symlinks into the ivy2 cache. This ensures that paths to jars
      # in artifact-cached analysis files are consistent across systems.
      # Note that we have one global, well-known symlink dir, again so that paths are
      # consistent across builds.
      symlink_dir = os.path.join(ivy_workdir, 'jars')
      symlink_map = IvyUtils.symlink_cachepath(ivy_cache_dir,
                                               raw_target_classpath_file,
                                               symlink_dir,
                                               target_classpath_file)
    return symlink_map
