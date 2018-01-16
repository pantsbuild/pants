# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import json
import logging
import os
import pkgutil
import threading
import xml.etree.ElementTree as ET
from abc import abstractmethod
from collections import OrderedDict, defaultdict, namedtuple

import six
from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.jar_dependency_management import (JarDependencyManagement,
                                                                    PinnedJarArtifactSet)
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.generator import Generator, TemplateData
from pants.base.revision import Revision
from pants.build_graph.target import Target
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.java.util import execute_runner
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir, safe_open
from pants.util.fileutil import atomic_copy


class IvyResolutionStep(object):
  """Ivy specific class for describing steps of performing resolution."""
  # NB(nh): This class is the base class for the ivy resolve and fetch steps.
  # It also specifies the abstract methods that define the components of resolution steps.

  def __init__(self, confs, hash_name, pinned_artifacts, soft_excludes, ivy_cache_dir,
               global_ivy_workdir):
    """
    :param confs: A tuple of string ivy confs to resolve for.
    :param hash_name: A unique string name for this resolve.
    :param pinned_artifacts: A tuple of "artifact-alikes" to force the versions of.
    :param soft_excludes: A flag marking whether to pass excludes to Ivy or to apply them after the
                          fact.
    :param ivy_cache_dir: The cache directory used by Ivy for this resolution step.
    :param global_ivy_workdir: The workdir that all ivy outputs live in.
    """

    self.confs = confs
    self.hash_name = hash_name
    self.pinned_artifacts = pinned_artifacts
    self.soft_excludes = soft_excludes

    self.ivy_cache_dir = ivy_cache_dir
    self.global_ivy_workdir = global_ivy_workdir

    self.workdir_reports_by_conf = {c: self.resolve_report_path(c) for c in confs}

  @abstractmethod
  def required_load_files_exist(self):
    """The files required to load a previous resolve exist."""

  @abstractmethod
  def required_exec_files_exist(self):
    """The files to do a resolve exist."""

  @abstractmethod
  def load(self, targets):
    """Loads the result of a resolve or fetch."""

  @abstractmethod
  def exec_and_load(self, executor, extra_args, targets, jvm_options, workunit_name,
                       workunit_factory):
    """Runs the resolve or fetch and loads the result, returning it."""

  @property
  def workdir(self):
    return os.path.join(self.global_ivy_workdir, self.hash_name)

  @property
  def symlink_classpath_filename(self):
    return os.path.join(self.workdir, 'classpath')

  @property
  def ivy_cache_classpath_filename(self):
    return '{}.raw'.format(self.symlink_classpath_filename)

  @property
  def frozen_resolve_file(self):
    return os.path.join(self.workdir, 'resolution.json')

  @property
  def symlink_dir(self):
    return os.path.join(self.global_ivy_workdir, 'jars')

  @abstractmethod
  def ivy_xml_path(self):
    """Ivy xml location."""

  @abstractmethod
  def resolve_report_path(self, conf):
    """Location of the resolve report in the workdir."""

  def _construct_and_load_symlink_map(self):
    artifact_paths, symlink_map = IvyUtils.construct_and_load_symlink_map(
      self.symlink_dir,
      self.ivy_cache_dir,
      self.ivy_cache_classpath_filename,
      self.symlink_classpath_filename)
    return artifact_paths, symlink_map

  def _call_ivy(self, executor, extra_args, ivyxml, jvm_options, hash_name_for_report,
                workunit_factory, workunit_name):
    IvyUtils.do_resolve(executor,
                        extra_args,
                        ivyxml,
                        jvm_options,
                        self.workdir_reports_by_conf,
                        self.confs,
                        self.ivy_cache_dir,
                        self.ivy_cache_classpath_filename,
                        hash_name_for_report,
                        workunit_factory,
                        workunit_name)


class IvyFetchStep(IvyResolutionStep):
  """Resolves ivy artifacts using the coordinates from a previous resolve."""

  def required_load_files_exist(self):
    return (all(os.path.isfile(report) for report in self.workdir_reports_by_conf.values()) and
                os.path.isfile(self.ivy_cache_classpath_filename) and
                os.path.isfile(self.frozen_resolve_file))

  def resolve_report_path(self, conf):
    return os.path.join(self.workdir, 'fetch-report-{}.xml'.format(conf))

  @property
  def ivy_xml_path(self):
    return os.path.join(self.workdir, 'fetch-ivy.xml')

  def required_exec_files_exist(self):
    return os.path.isfile(self.frozen_resolve_file)

  def load(self, targets):
    try:
      frozen_resolutions = FrozenResolution.load_from_file(self.frozen_resolve_file,
                                                         targets)
    except Exception as e:
      logger.debug('Failed to load {}: {}'.format(self.frozen_resolve_file, e))
      return NO_RESOLVE_RUN_RESULT
    return self._load_from_fetch(frozen_resolutions)

  def exec_and_load(self, executor, extra_args, targets, jvm_options, workunit_name,
                       workunit_factory):
    try:
      frozen_resolutions = FrozenResolution.load_from_file(self.frozen_resolve_file,
                                                         targets)
    except Exception as e:
      logger.debug('Failed to load {}: {}'.format(self.frozen_resolve_file, e))
      return NO_RESOLVE_RUN_RESULT

    self._do_fetch(executor, extra_args, frozen_resolutions, jvm_options,
                           workunit_name, workunit_factory)
    result = self._load_from_fetch(frozen_resolutions)

    if not result.all_linked_artifacts_exist():
      raise IvyResolveMappingError(
        'Some artifacts were not linked to {} for {}'.format(self.global_ivy_workdir,
                                                             result))
    return result

  def _load_from_fetch(self, frozen_resolutions):
    artifact_paths, symlink_map = self._construct_and_load_symlink_map()
    return IvyFetchResolveResult(artifact_paths,
                                 symlink_map,
                                 self.hash_name,
                                 self.workdir_reports_by_conf,
                                 frozen_resolutions)

  def _do_fetch(self, executor, extra_args, frozen_resolution, jvm_options, workunit_name,
                        workunit_factory):
    # It's important for fetches to have a different ivy report from resolves as their
    # contents differ.
    hash_name_for_report = '{}-fetch'.format(self.hash_name)

    ivyxml = self.ivy_xml_path
    self._prepare_ivy_xml(frozen_resolution, ivyxml, hash_name_for_report)

    self._call_ivy(executor, extra_args, ivyxml, jvm_options, hash_name_for_report,
                   workunit_factory, workunit_name)

  def _prepare_ivy_xml(self, frozen_resolution, ivyxml, resolve_hash_name_for_report):
    # NB(nh): Our ivy.xml ensures that we always get the default configuration, even if it's not
    # part of the requested confs.
    default_resolution = frozen_resolution.get('default')
    if default_resolution is None:
      raise IvyUtils.IvyError("Couldn't find the frozen resolution for the 'default' ivy conf.")

    try:
      jars = default_resolution.jar_dependencies
      IvyUtils.generate_fetch_ivy(jars, ivyxml, self.confs, resolve_hash_name_for_report)
    except Exception as e:
      raise IvyUtils.IvyError('Failed to prepare ivy resolve: {}'.format(e))


class IvyResolveStep(IvyResolutionStep):
  """Resolves ivy artifacts and produces a cacheable file containing the resulting coordinates."""

  def required_load_files_exist(self):
    return (all(os.path.isfile(report) for report in self.workdir_reports_by_conf.values()) and
                os.path.isfile(self.ivy_cache_classpath_filename))

  def resolve_report_path(self, conf):
    return os.path.join(self.workdir, 'resolve-report-{}.xml'.format(conf))

  @property
  def ivy_xml_path(self):
    return os.path.join(self.workdir, 'resolve-ivy.xml')

  def load(self, targets):
    artifact_paths, symlink_map = self._construct_and_load_symlink_map()
    return IvyResolveResult(artifact_paths,
                            symlink_map,
                            self.hash_name,
                            self.workdir_reports_by_conf)

  def exec_and_load(self, executor, extra_args, targets, jvm_options,
                       workunit_name, workunit_factory):
    self._do_resolve(executor, extra_args, targets, jvm_options, workunit_name, workunit_factory)
    result = self.load(targets)

    if not result.all_linked_artifacts_exist():
      raise IvyResolveMappingError(
        'Some artifacts were not linked to {} for {}'.format(self.global_ivy_workdir,
                                                             result))

    frozen_resolutions_by_conf = result.get_frozen_resolutions_by_conf(targets)
    FrozenResolution.dump_to_file(self.frozen_resolve_file, frozen_resolutions_by_conf)
    return result

  def _do_resolve(self, executor, extra_args, targets, jvm_options, workunit_name, workunit_factory):
    ivyxml = self.ivy_xml_path
    hash_name = '{}-resolve'.format(self.hash_name)
    self._prepare_ivy_xml(targets, ivyxml, hash_name)

    self._call_ivy(executor, extra_args, ivyxml, jvm_options, hash_name,
                   workunit_factory, workunit_name)

  def _prepare_ivy_xml(self, targets, ivyxml, hash_name):
    # TODO(John Sirois): merge the code below into IvyUtils or up here; either way, better
    # diagnostics can be had in `IvyUtils.generate_ivy` if this is done.
    # See: https://github.com/pantsbuild/pants/issues/2239
    jars, global_excludes = IvyUtils.calculate_classpath(targets)

    # Don't pass global excludes to ivy when using soft excludes.
    if self.soft_excludes:
      global_excludes = []

    IvyUtils.generate_ivy(targets, jars, global_excludes, ivyxml, self.confs,
                          hash_name, self.pinned_artifacts)


class FrozenResolution(object):
  """Contains the abstracted results of a resolve.

  With this we can do a simple fetch.
  """
  # TODO(nh): include full dependency graph in here.
  # So that we can inject it into the build graph if we want to.

  class MissingTarget(Exception):
    """Thrown when a loaded resolution has a target spec for a target that doesn't exist."""

  def __init__(self):
    self.target_to_resolved_coordinates = defaultdict(OrderedSet)
    self.all_resolved_coordinates = OrderedSet()
    self.coordinate_to_attributes = OrderedDict()

  @property
  def jar_dependencies(self):
    return [
      JarDependency(c.org, c.name, c.rev, classifier=c.classifier, ext=c.ext,
                    **self.coordinate_to_attributes.get(c, {}))
      for c in self.all_resolved_coordinates]

  def add_resolved_jars(self, target, resolved_jars):
    coords = [j.coordinate for j in resolved_jars]
    self.add_resolution_coords(target, coords)

    # Assuming target is a jar library.
    for j in target.jar_dependencies:
      url = j.get_url(relative=True)
      if url:
        self.coordinate_to_attributes[j.coordinate] = {'url': url, 'base_path': j.base_path}
      else:
        self.coordinate_to_attributes[j.coordinate] = {}

  def add_resolution_coords(self, target, coords):
    for c in coords:
      self.target_to_resolved_coordinates[target].add(c)
      self.all_resolved_coordinates.add(c)

  def target_spec_to_coordinate_strings(self):
    return {t.address.spec: [str(c) for c in coordinates]
            for t, coordinates in self.target_to_resolved_coordinates.items()}

  def __repr__(self):
    return 'FrozenResolution(\n  target_to_resolved_coordinates\n    {}\n  all\n    {}'.format(
      '\n    '.join(':  '.join([t.address.spec,
                                '\n      '.join(str(c) for c in cs)])
                    for t,cs in self.target_to_resolved_coordinates.items()),
      '\n    '.join(str(c) for c in self.coordinate_to_attributes.keys())
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

      def m2_for(c):
        return M2Coordinate.from_string(c)

      for coord, attr_dict in serialized_resolution['coord_to_attrs'].items():
        m2 = m2_for(coord)
        resolution.coordinate_to_attributes[m2] = attr_dict

      for spec, coord_strs in serialized_resolution['target_to_coords'].items():
        t = target_lookup.get(spec, None)
        if t is None:
          raise cls.MissingTarget('Cannot find target for address {} in frozen resolution'
                                  .format(spec))
        resolution.add_resolution_coords(t, [m2_for(c) for c in coord_strs])
      result[conf] = resolution

    return result

  @classmethod
  def dump_to_file(cls, filename, resolutions_by_conf):
    res = {}
    for conf, resolution in resolutions_by_conf.items():
      res[conf] = OrderedDict([
        ['target_to_coords',resolution.target_spec_to_coordinate_strings()],
        ['coord_to_attrs', OrderedDict([str(c), attrs]
                                       for c, attrs in resolution.coordinate_to_attributes.items())]
      ])

    with safe_concurrent_creation(filename) as tmp_filename:
      with open(tmp_filename, 'wb') as f:
        json.dump(res, f)


class IvyResolveResult(object):
  """The result of an Ivy resolution.

  The result data includes the list of resolved artifacts, the relationships between those artifacts
  and the targets that requested them and the hash name of the resolve.
  """

  def __init__(self, resolved_artifact_paths, symlink_map, resolve_hash_name, reports_by_conf):
    self._reports_by_conf = reports_by_conf
    self.resolved_artifact_paths = resolved_artifact_paths
    self.resolve_hash_name = resolve_hash_name
    self._symlink_map = symlink_map

  @property
  def has_resolved_artifacts(self):
    """The requested targets have a resolution associated with them."""
    return self.resolve_hash_name is not None

  def all_linked_artifacts_exist(self):
    """All of the artifact paths for this resolve point to existing files."""
    if not self.has_resolved_artifacts:
      return False
    for path in self.resolved_artifact_paths:
      if not os.path.isfile(path):
        return False
    else:
      return True

  def report_for_conf(self, conf):
    """Returns the path to the ivy report for the provided conf.

     Returns None if there is no path.
    """
    return self._reports_by_conf.get(conf)

  def get_frozen_resolutions_by_conf(self, targets):
    frozen_resolutions_by_conf = OrderedDict()
    for conf in self._reports_by_conf:
      frozen_resolution = FrozenResolution()
      for target, resolved_jars in self.resolved_jars_for_each_target(conf, targets):
        frozen_resolution.add_resolved_jars(target, resolved_jars)
      frozen_resolutions_by_conf[conf] = frozen_resolution
    return frozen_resolutions_by_conf

  def resolved_jars_for_each_target(self, conf, targets):
    """Yields the resolved jars for each passed JarLibrary.

    If there is no report for the requested conf, yields nothing.

    :param conf: The ivy conf to load jars for.
    :param targets: The collection of JarLibrary targets to find resolved jars for.
    :yield: target, resolved_jars
    :raises IvyTaskMixin.UnresolvedJarError
    """
    ivy_info = self._ivy_info_for(conf)

    if not ivy_info:
      return

    jar_library_targets = [t for t in targets if isinstance(t, JarLibrary)]
    ivy_jar_memo = {}
    for target in jar_library_targets:
      # Add the artifacts from each dependency module.
      resolved_jars = self._resolved_jars_with_symlinks(conf, ivy_info, ivy_jar_memo,
                                                        self._jar_dependencies_for_target(conf,
                                                                                          target),
                                                        target)
      yield target, resolved_jars

  def _jar_dependencies_for_target(self, conf, target):
    return target.jar_dependencies

  def _ivy_info_for(self, conf):
    report_path = self._reports_by_conf.get(conf)
    return IvyUtils.parse_xml_report(conf, report_path)

  def _new_resolved_jar_with_symlink_path(self, conf, target, resolved_jar_without_symlink):
    def candidate_cache_paths():
      # There is a focus on being lazy here to avoid `os.path.realpath` when we can.
      yield resolved_jar_without_symlink.cache_path
      yield os.path.realpath(resolved_jar_without_symlink.cache_path)

    for cache_path in candidate_cache_paths():
      pants_path = self._symlink_map.get(cache_path)
      if pants_path:
        break
    else:

      raise IvyResolveMappingError(
        'Jar {resolved_jar} in {spec} not resolved to the ivy '
        'symlink map in conf {conf}.'
          .format(spec=target.address.spec,
                  resolved_jar=resolved_jar_without_symlink.cache_path,
                  conf=conf))

    return ResolvedJar(coordinate=resolved_jar_without_symlink.coordinate,
                       pants_path=pants_path,
                       cache_path=resolved_jar_without_symlink.cache_path)

  def _resolved_jars_with_symlinks(self, conf, ivy_info, ivy_jar_memo, coordinates, target):
    raw_resolved_jars = ivy_info.get_resolved_jars_for_coordinates(coordinates,
                                                                   memo=ivy_jar_memo)
    resolved_jars = [self._new_resolved_jar_with_symlink_path(conf, target, raw_resolved_jar)
                     for raw_resolved_jar in raw_resolved_jars]
    return resolved_jars


class IvyFetchResolveResult(IvyResolveResult):
  """A resolve result that uses the frozen resolution to look up dependencies."""

  def __init__(self, resolved_artifact_paths, symlink_map, resolve_hash_name, reports_by_conf,
               frozen_resolutions):
    super(IvyFetchResolveResult, self).__init__(resolved_artifact_paths, symlink_map,
                                                resolve_hash_name, reports_by_conf)
    self._frozen_resolutions = frozen_resolutions

  def _jar_dependencies_for_target(self, conf, target):
    return self._frozen_resolutions[conf].target_to_resolved_coordinates.get(target, ())


NO_RESOLVE_RUN_RESULT = IvyResolveResult([], {}, None, {})


IvyModule = namedtuple('IvyModule', ['ref', 'artifact', 'callers'])


Dependency = namedtuple('DependencyAttributes',
                        ['org', 'name', 'rev', 'mutable', 'force', 'transitive'])


Artifact = namedtuple('Artifact', ['name', 'type_', 'ext', 'url', 'classifier'])


logger = logging.getLogger(__name__)


class IvyResolveMappingError(Exception):
  """Raised when there is a failure mapping the ivy resolve results to pants objects."""


class IvyModuleRef(object):
  """
  :API: public
  """

  # latest.integration is ivy magic meaning "just get the latest version"
  _ANY_REV = 'latest.integration'

  def __init__(self, org, name, rev, classifier=None, ext=None):
    self.org = org
    self.name = name
    self.rev = rev
    self.classifier = classifier
    self.ext = ext or 'jar'

    self._id = (self.org, self.name, self.rev, self.classifier, self.ext)

  def __eq__(self, other):
    return isinstance(other, IvyModuleRef) and self._id == other._id

  def __ne__(self, other):
    return not self == other

  def __hash__(self):
    return hash(self._id)

  def __str__(self):
    return 'IvyModuleRef({})'.format(':'.join((x or '') for x in self._id))

  def __repr__(self):
    return ('IvyModuleRef(org={!r}, name={!r}, rev={!r}, classifier={!r}, ext={!r})'
            .format(*self._id))

  def __cmp__(self, other):
    # We can't just re-use __repr__ or __str_ because we want to order rev last
    return cmp((self.org, self.name, self.classifier, self.ext, self.rev),
               (other.org, other.name, other.classifier, other.ext, other.rev))

  @property
  def caller_key(self):
    """This returns an identifier for an IvyModuleRef that only retains the caller org and name.

    Ivy represents dependees as `<caller/>`'s with just org and name and rev information.
    This method returns a `<caller/>` representation of the current ref.
    """
    return IvyModuleRef(name=self.name, org=self.org, rev=self._ANY_REV)

  @property
  def unversioned(self):
    """This returns an identifier for an IvyModuleRef without version information.

    It's useful because ivy might return information about a different version of a dependency than
    the one we request, and we want to ensure that all requesters of any version of that dependency
    are able to learn about it.
    """
    return IvyModuleRef(name=self.name, org=self.org, rev=self._ANY_REV, classifier=self.classifier,
                        ext=self.ext)


class IvyInfo(object):
  """
  :API: public
  """

  def __init__(self, conf):
    self._conf = conf
    self.modules_by_ref = {}  # Map from ref to referenced module.
    self.refs_by_unversioned_refs = {} # Map from unversioned ref to the resolved versioned ref
    # Map from ref of caller to refs of modules required by that caller.
    self._deps_by_caller = defaultdict(OrderedSet)
    # Map from _unversioned_ ref to OrderedSet of IvyArtifact instances.
    self._artifacts_by_ref = defaultdict(OrderedSet)

  def add_module(self, module):
    if not module.artifact:
      # Module was evicted, so do not record information about it
      return

    ref_unversioned = module.ref.unversioned
    if ref_unversioned in self.refs_by_unversioned_refs:
      raise IvyResolveMappingError('Already defined module {}, as rev {}!'
                                   .format(ref_unversioned, module.ref.rev))
    if module.ref in self.modules_by_ref:
      raise IvyResolveMappingError('Already defined module {}, would be overwritten!'
                                   .format(module.ref))
    self.refs_by_unversioned_refs[ref_unversioned] = module.ref
    self.modules_by_ref[module.ref] = module

    for caller in module.callers:
      self._deps_by_caller[caller.caller_key].add(module.ref)
    self._artifacts_by_ref[ref_unversioned].add(module.artifact)

  def _do_traverse_dependency_graph(self, ref, collector, memo, visited):
    memoized_value = memo.get(ref)
    if memoized_value:
      return memoized_value

    if ref in visited:
      # Ivy allows for circular dependencies
      # If we're here, that means we're resolving something that
      # transitively depends on itself
      return set()

    visited.add(ref)
    acc = collector(ref)
    # NB(zundel): ivy does not return deps in a consistent order for the same module for
    # different resolves.  Sort them to get consistency and prevent cache invalidation.
    # See https://github.com/pantsbuild/pants/issues/2607
    deps = sorted(self._deps_by_caller.get(ref.caller_key, ()))
    for dep in deps:
      acc.update(self._do_traverse_dependency_graph(dep, collector, memo, visited))
    memo[ref] = acc
    return acc

  def traverse_dependency_graph(self, ref, collector, memo=None):
    """Traverses module graph, starting with ref, collecting values for each ref into the sets
    created by the collector function.

    :param ref an IvyModuleRef to start traversing the ivy dependency graph
    :param collector a function that takes a ref and returns a new set of values to collect for
           that ref, which will also be updated with all the dependencies accumulated values
    :param memo is a dict of ref -> set that memoizes the results of each node in the graph.
           If provided, allows for retaining cache across calls.
    :returns the accumulated set for ref
    """

    resolved_ref = self.refs_by_unversioned_refs.get(ref.unversioned)
    if resolved_ref:
      ref = resolved_ref
    if memo is None:
      memo = dict()
    visited = set()
    return self._do_traverse_dependency_graph(ref, collector, memo, visited)

  def get_resolved_jars_for_coordinates(self, coordinates, memo=None):
    """Collects jars for the passed coordinates.

    Because artifacts are only fetched for the "winning" version of a module, the artifacts
    will not always represent the version originally declared by the library.

    This method is transitive within the passed coordinates dependencies.

    :param coordinates collections.Iterable: Collection of coordinates to collect transitive
                                             resolved jars for.
    :param memo: See `traverse_dependency_graph`.
    :returns: All the artifacts for all of the jars for the provided coordinates,
              including transitive dependencies.
    :rtype: list of :class:`pants.java.jar.ResolvedJar`
    """
    def to_resolved_jar(jar_ref, jar_path):
      return ResolvedJar(coordinate=M2Coordinate(org=jar_ref.org,
                                                 name=jar_ref.name,
                                                 rev=jar_ref.rev,
                                                 classifier=jar_ref.classifier,
                                                 ext=jar_ref.ext),
                         cache_path=jar_path)
    resolved_jars = OrderedSet()
    def create_collection(dep):
      return OrderedSet([dep])
    for jar in coordinates:
      classifier = jar.classifier if self._conf == 'default' else self._conf
      jar_module_ref = IvyModuleRef(jar.org, jar.name, jar.rev, classifier, jar.ext)
      for module_ref in self.traverse_dependency_graph(jar_module_ref, create_collection, memo):
        for artifact_path in self._artifacts_by_ref[module_ref.unversioned]:
          resolved_jars.add(to_resolved_jar(module_ref, artifact_path))
    return resolved_jars

  def __repr__(self):
    return 'IvyInfo(conf={}, refs={})'.format(self._conf, self.modules_by_ref.keys())


class IvyUtils(object):
  """Useful methods related to interaction with ivy.

  :API: public
  """

  # Protects ivy executions.
  _ivy_lock = threading.RLock()

  # Protect writes to the global map of jar path -> symlinks to that jar.
  _symlink_map_lock = threading.Lock()

  INTERNAL_ORG_NAME = 'internal'

  class IvyError(Exception):
    """Indicates an error preparing an ivy operation."""

  class IvyResolveReportError(IvyError):
    """Indicates that an ivy report cannot be found."""

  class IvyResolveConflictingDepsError(IvyError):
    """Indicates two or more locally declared dependencies conflict."""

  class BadRevisionError(IvyError):
    """Indicates an unparseable version number."""

  @staticmethod
  def _generate_exclude_template(exclude):
    return TemplateData(org=exclude.org, name=exclude.name)

  @staticmethod
  def _generate_override_template(jar):
    return TemplateData(org=jar.org, module=jar.name, version=jar.rev)

  @staticmethod
  def _load_classpath_from_cachepath(path):
    if not os.path.exists(path):
      return []
    else:
      with safe_open(path, 'r') as cp:
        return filter(None, (path.strip() for path in cp.read().split(os.pathsep)))

  @classmethod
  def do_resolve(cls, executor, extra_args, ivyxml, jvm_options, workdir_report_paths_by_conf,
                 confs, ivy_cache_dir, ivy_cache_classpath_filename, resolve_hash_name,
                 workunit_factory, workunit_name):
    """Execute Ivy with the given ivy.xml and copies all relevant files into the workdir.

    This method does an Ivy resolve, which may be either a Pants resolve or a Pants fetch depending
    on whether there is an existing frozen resolution.

    After it is run, the Ivy reports are copied into the workdir at the paths specified by
    workdir_report_paths_by_conf along with a file containing a list of all the requested artifacts
    and their transitive dependencies.

    :param executor: A JVM executor to use to invoke ivy.
    :param extra_args: Extra arguments to pass to ivy.
    :param ivyxml: The input ivy.xml containing the dependencies to resolve.
    :param jvm_options: A list of jvm option strings to use for the ivy invoke, or None.
    :param workdir_report_paths_by_conf: A dict mapping confs to report paths in the workdir.
    :param confs: The confs used in the resolve.
    :param resolve_hash_name: The hash to use as the module name for finding the ivy report file.
    :param workunit_factory: A workunit factory for the ivy invoke, or None.
    :param workunit_name: A workunit name for the ivy invoke, or None.
    """
    ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=workunit_factory)

    with safe_concurrent_creation(ivy_cache_classpath_filename) as raw_target_classpath_file_tmp:
      extra_args = extra_args or []
      args = ['-cachepath', raw_target_classpath_file_tmp] + extra_args

      with cls._ivy_lock:
        cls._exec_ivy(ivy, confs, ivyxml, args,
                      jvm_options=jvm_options,
                      executor=executor,
                      workunit_name=workunit_name,
                      workunit_factory=workunit_factory)

      if not os.path.exists(raw_target_classpath_file_tmp):
        raise cls.IvyError('Ivy failed to create classpath file at {}'
                           .format(raw_target_classpath_file_tmp))

      cls._copy_ivy_reports(workdir_report_paths_by_conf, confs, ivy_cache_dir, resolve_hash_name)

    logger.debug('Moved ivy classfile file to {dest}'
                 .format(dest=ivy_cache_classpath_filename))

  @classmethod
  def _copy_ivy_reports(cls, workdir_report_paths_by_conf, confs, ivy_cache_dir, resolve_hash_name):
    for conf in confs:
      ivy_cache_report_path = IvyUtils.xml_report_path(ivy_cache_dir, resolve_hash_name,
                                                       conf)
      workdir_report_path = workdir_report_paths_by_conf[conf]
      try:
        atomic_copy(ivy_cache_report_path,
                    workdir_report_path)
      except IOError as e:
        raise cls.IvyError('Failed to copy report into workdir from {} to {}: {}'
                           .format(ivy_cache_report_path, workdir_report_path, e))

  @classmethod
  def _exec_ivy(cls, ivy, confs, ivyxml, args, jvm_options, executor,
                workunit_name, workunit_factory):
    ivy = ivy or Bootstrapper.default_ivy()

    ivy_args = ['-ivy', ivyxml]
    ivy_args.append('-confs')
    ivy_args.extend(confs)
    ivy_args.extend(args)

    ivy_jvm_options = list(jvm_options)
    # Disable cache in File.getCanonicalPath(), makes Ivy work with -symlink option properly on ng.
    ivy_jvm_options.append('-Dsun.io.useCanonCaches=false')

    runner = ivy.runner(jvm_options=ivy_jvm_options, args=ivy_args, executor=executor)
    try:
      with ivy.resolution_lock:
        result = execute_runner(runner, workunit_factory=workunit_factory,
                                workunit_name=workunit_name)
      if result != 0:
        raise IvyUtils.IvyError('Ivy returned {result}. cmd={cmd}'.format(result=result,
                                                                          cmd=runner.cmd))
    except runner.executor.Error as e:
      raise IvyUtils.IvyError(e)

  @classmethod
  def construct_and_load_symlink_map(cls, symlink_dir, ivy_cache_dir,
                                     ivy_cache_classpath_filename, symlink_classpath_filename):
    # Make our actual classpath be symlinks, so that the paths are uniform across systems.
    # Note that we must do this even if we read the raw_target_classpath_file from the artifact
    # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
    with IvyUtils._symlink_map_lock:
      # A common dir for symlinks into the ivy2 cache. This ensures that paths to jars
      # in artifact-cached analysis files are consistent across systems.
      # Note that we have one global, well-known symlink dir, again so that paths are
      # consistent across builds.
      symlink_map = cls._symlink_cachepath(ivy_cache_dir,
                                           ivy_cache_classpath_filename,
                                           symlink_dir,
                                           symlink_classpath_filename)
    classpath = cls._load_classpath_from_cachepath(symlink_classpath_filename)
    return classpath, symlink_map

  @classmethod
  def _symlink_cachepath(cls, ivy_cache_dir, inpath, symlink_dir, outpath):
    """Symlinks all paths listed in inpath that are under ivy_cache_dir into symlink_dir.

    If there is an existing symlink for a file under inpath, it is used rather than creating
    a new symlink. Preserves all other paths. Writes the resulting paths to outpath.
    Returns a map of path -> symlink to that path.
    """
    safe_mkdir(symlink_dir)
    # The ivy_cache_dir might itself be a symlink. In this case, ivy may return paths that
    # reference the realpath of the .jar file after it is resolved in the cache dir. To handle
    # this case, add both the symlink'ed path and the realpath to the jar to the symlink map.
    real_ivy_cache_dir = os.path.realpath(ivy_cache_dir)
    symlink_map = OrderedDict()

    inpaths = cls._load_classpath_from_cachepath(inpath)
    paths = OrderedSet([os.path.realpath(path) for path in inpaths])

    for path in paths:
      if path.startswith(real_ivy_cache_dir):
        symlink_map[path] = os.path.join(symlink_dir, os.path.relpath(path, real_ivy_cache_dir))
      else:
        # This path is outside the cache. We won't symlink it.
        symlink_map[path] = path

    # Create symlinks for paths in the ivy cache dir.
    for path, symlink in six.iteritems(symlink_map):
      if path == symlink:
        # Skip paths that aren't going to be symlinked.
        continue
      safe_mkdir(os.path.dirname(symlink))
      try:
        os.symlink(path, symlink)
      except OSError as e:
        # We don't delete and recreate the symlink, as this may break concurrently executing code.
        if e.errno != errno.EEXIST:
          raise

    # (re)create the classpath with all of the paths
    with safe_open(outpath, 'w') as outfile:
      outfile.write(':'.join(OrderedSet(symlink_map.values())))

    return dict(symlink_map)

  @classmethod
  def xml_report_path(cls, cache_dir, resolve_hash_name, conf):
    """The path to the xml report ivy creates after a retrieve.

    :API: public

    :param string cache_dir: The path of the ivy cache dir used for resolves.
    :param string resolve_hash_name: Hash from the Cache key from the VersionedTargetSet used for
                                     resolution.
    :param string conf: The ivy conf name (e.g. "default").
    :returns: The report path.
    :rtype: string
    """
    return os.path.join(cache_dir, '{}-{}-{}.xml'.format(IvyUtils.INTERNAL_ORG_NAME,
                                                         resolve_hash_name, conf))

  @classmethod
  def parse_xml_report(cls, conf, path):
    """Parse the ivy xml report corresponding to the name passed to ivy.

    :API: public

    :param string conf: the ivy conf name (e.g. "default")
    :param string path: The path to the ivy report file.
    :returns: The info in the xml report.
    :rtype: :class:`IvyInfo`
    :raises: :class:`IvyResolveMappingError` if no report exists.
    """
    if not os.path.exists(path):
      raise cls.IvyResolveReportError('Missing expected ivy output file {}'.format(path))

    logger.debug("Parsing ivy report {}".format(path))
    ret = IvyInfo(conf)
    etree = ET.parse(path)
    doc = etree.getroot()
    for module in doc.findall('dependencies/module'):
      org = module.get('organisation')
      name = module.get('name')
      for revision in module.findall('revision'):
        rev = revision.get('name')
        callers = []
        for caller in revision.findall('caller'):
          callers.append(IvyModuleRef(caller.get('organisation'),
                                      caller.get('name'),
                                      caller.get('callerrev')))

        for artifact in revision.findall('artifacts/artifact'):
          classifier = artifact.get('extra-classifier')
          ext = artifact.get('ext')
          ivy_module_ref = IvyModuleRef(org=org, name=name, rev=rev,
                                        classifier=classifier, ext=ext)

          artifact_cache_path = artifact.get('location')
          ivy_module = IvyModule(ivy_module_ref, artifact_cache_path, tuple(callers))

          ret.add_module(ivy_module)
    return ret

  @classmethod
  def generate_ivy(cls, targets, jars, excludes, ivyxml, confs, resolve_hash_name=None,
                   pinned_artifacts=None, jar_dep_manager=None):
    if not resolve_hash_name:
      resolve_hash_name = Target.maybe_readable_identify(targets)
    return cls._generate_resolve_ivy(jars, excludes, ivyxml, confs, resolve_hash_name, pinned_artifacts,
                             jar_dep_manager)

  @classmethod
  def _generate_resolve_ivy(cls, jars, excludes, ivyxml, confs, resolve_hash_name, pinned_artifacts=None,
                    jar_dep_manager=None):
    org = IvyUtils.INTERNAL_ORG_NAME
    name = resolve_hash_name

    extra_configurations = [conf for conf in confs if conf and conf != 'default']

    jars_by_key = OrderedDict()
    for jar in jars:
      jars = jars_by_key.setdefault((jar.org, jar.name), [])
      jars.append(jar)

    manager = jar_dep_manager or JarDependencyManagement.global_instance()
    artifact_set = PinnedJarArtifactSet(pinned_artifacts) # Copy, because we're modifying it.
    for jars in jars_by_key.values():
      for i, dep in enumerate(jars):
        direct_coord = M2Coordinate.create(dep)
        managed_coord = artifact_set[direct_coord]
        if direct_coord.rev != managed_coord.rev:
          # It may be necessary to actually change the version number of the jar we want to resolve
          # here, because overrides do not apply directly (they are exclusively transitive). This is
          # actually a good thing, because it gives us more control over what happens.
          coord = manager.resolve_version_conflict(managed_coord, direct_coord, force=dep.force)
          jars[i] = dep.copy(rev=coord.rev)
        elif dep.force:
          # If this dependency is marked as 'force' and there is no version conflict, use the normal
          # pants behavior for 'force'.
          artifact_set.put(direct_coord)

    dependencies = [cls._generate_jar_template(jars) for jars in jars_by_key.values()]

    # As it turns out force is not transitive - it only works for dependencies pants knows about
    # directly (declared in BUILD files - present in generated ivy.xml). The user-level ivy docs
    # don't make this clear [1], but the source code docs do (see isForce docs) [2]. I was able to
    # edit the generated ivy.xml and use the override feature [3] though and that does work
    # transitively as you'd hope.
    #
    # [1] http://ant.apache.org/ivy/history/2.3.0/settings/conflict-managers.html
    # [2] https://svn.apache.org/repos/asf/ant/ivy/core/branches/2.3.0/
    #     src/java/org/apache/ivy/core/module/descriptor/DependencyDescriptor.java
    # [3] http://ant.apache.org/ivy/history/2.3.0/ivyfile/override.html
    overrides = [cls._generate_override_template(_coord) for _coord in artifact_set]

    excludes = [cls._generate_exclude_template(exclude) for exclude in excludes]

    template_data = TemplateData(
      org=org,
      module=name,
      extra_configurations=extra_configurations,
      dependencies=dependencies,
      excludes=excludes,
      overrides=overrides)

    template_relpath = os.path.join('templates', 'ivy_utils', 'ivy.xml.mustache')
    cls._write_ivy_xml_file(ivyxml, template_data, template_relpath)

  @classmethod
  def generate_fetch_ivy(cls, jars, ivyxml, confs, resolve_hash_name):
    """Generates an ivy xml with all jars marked as intransitive using the all conflict manager."""
    org = IvyUtils.INTERNAL_ORG_NAME
    name = resolve_hash_name

    extra_configurations = [conf for conf in confs if conf and conf != 'default']

    # Use org name _and_ rev so that we can have dependencies with different versions. This will
    # allow for batching fetching if we want to do that.
    jars_by_key = OrderedDict()
    for jar in jars:
      jars_by_key.setdefault((jar.org, jar.name, jar.rev), []).append(jar)


    dependencies = [cls._generate_fetch_jar_template(_jars) for _jars in jars_by_key.values()]

    template_data = TemplateData(org=org,
                                 module=name,
                                 extra_configurations=extra_configurations,
                                 dependencies=dependencies)

    template_relpath = os.path.join('templates', 'ivy_utils', 'ivy_fetch.xml.mustache')
    cls._write_ivy_xml_file(ivyxml, template_data, template_relpath)

  @classmethod
  def _write_ivy_xml_file(cls, ivyxml, template_data, template_relpath):
    template_text = pkgutil.get_data(__name__, template_relpath)
    generator = Generator(template_text, lib=template_data)
    with safe_open(ivyxml, 'w') as output:
      generator.write(output)

  @classmethod
  def calculate_classpath(cls, targets):
    """Creates a consistent classpath and list of excludes for the passed targets.

    It also modifies the JarDependency objects' excludes to contain all the jars excluded by
    provides.

    :param iterable targets: List of targets to collect JarDependencies and excludes from.

    :returns: A pair of a list of JarDependencies, and a set of excludes to apply globally.
    """
    jars = OrderedDict()
    global_excludes = set()
    provide_excludes = set()
    targets_processed = set()

    # Support the ivy force concept when we sanely can for internal dep conflicts.
    # TODO(John Sirois): Consider supporting / implementing the configured ivy revision picking
    # strategy generally.
    def add_jar(jar):
      # TODO(John Sirois): Maven allows for depending on an artifact at one rev and one of its
      # attachments (classified artifacts) at another.  Ivy does not, allow this, the dependency
      # can carry only 1 rev and that hosts multiple artifacts for that rev.  This conflict
      # resolution happens at the classifier level, allowing skew in a
      # multi-artifact/multi-classifier dependency.  We only find out about the skew later in
      # `_generate_jar_template` below which will blow up with a conflict.  Move this logic closer
      # together to get a more clear validate, then emit ivy.xml then resolve flow instead of the
      # spread-out validations happening here.
      # See: https://github.com/pantsbuild/pants/issues/2239
      coordinate = (jar.org, jar.name, jar.classifier)
      existing = jars.get(coordinate)
      jars[coordinate] = jar if not existing else cls._resolve_conflict(existing=existing,
                                                                        proposed=jar)

    def collect_jars(target):
      if isinstance(target, JarLibrary):
        for jar in target.jar_dependencies:
          add_jar(jar)

    def collect_excludes(target):
      target_excludes = target.payload.get_field_value('excludes')
      if target_excludes:
        global_excludes.update(target_excludes)

    def collect_provide_excludes(target):
      if not (isinstance(target, ExportableJvmLibrary) and target.provides):
        return
      logger.debug('Automatically excluding jar {}.{}, which is provided by {}'.format(
        target.provides.org, target.provides.name, target))
      provide_excludes.add(Exclude(org=target.provides.org, name=target.provides.name))

    def collect_elements(target):
      targets_processed.add(target)
      collect_jars(target)
      collect_excludes(target)
      collect_provide_excludes(target)

    for target in targets:
      target.walk(collect_elements, predicate=lambda target: target not in targets_processed)

    # If a source dep is exported (ie, has a provides clause), it should always override
    # remote/binary versions of itself, ie "round trip" dependencies.
    # TODO: Move back to applying provides excludes as target-level excludes when they are no
    # longer global.
    if provide_excludes:
      additional_excludes = tuple(provide_excludes)
      new_jars = OrderedDict()
      for coordinate, jar in jars.items():
        new_jars[coordinate] = jar.copy(excludes=jar.excludes + additional_excludes)
      jars = new_jars

    return jars.values(), global_excludes

  @classmethod
  def _resolve_conflict(cls, existing, proposed):
    if existing.rev is None:
      return proposed
    if proposed.rev is None:
      return existing
    if proposed == existing:
      if proposed.force:
        return proposed
      return existing
    elif existing.force and proposed.force:
      raise cls.IvyResolveConflictingDepsError('Cannot force {}#{};{} to both rev {} and {}'.format(
        proposed.org, proposed.name, proposed.classifier or '', existing.rev, proposed.rev
      ))
    elif existing.force:
      logger.debug('Ignoring rev {} for {}#{};{} already forced to {}'.format(
        proposed.rev, proposed.org, proposed.name, proposed.classifier or '', existing.rev
      ))
      return existing
    elif proposed.force:
      logger.debug('Forcing {}#{};{} from {} to {}'.format(
        proposed.org, proposed.name, proposed.classifier or '', existing.rev, proposed.rev
      ))
      return proposed
    else:
      if Revision.lenient(proposed.rev) > Revision.lenient(existing.rev):
        logger.debug('Upgrading {}#{};{} from rev {}  to {}'.format(
          proposed.org, proposed.name, proposed.classifier or '', existing.rev, proposed.rev,
        ))
        return proposed
      else:
        return existing

  @classmethod
  def _generate_jar_template(cls, jars):
    global_dep_attributes = set(Dependency(org=jar.org,
                                           name=jar.name,
                                           rev=jar.rev,
                                           mutable=jar.mutable,
                                           force=jar.force,
                                           transitive=jar.transitive)
                                for jar in jars)
    if len(global_dep_attributes) != 1:
      # TODO: Need to provide information about where these came from - could be
      # far-flung JarLibrary targets. The jars here were collected from targets via
      # `calculate_classpath` above so executing this step there instead may make more
      # sense.
      conflicting_dependencies = sorted(str(g) for g in global_dep_attributes)
      raise cls.IvyResolveConflictingDepsError('Found conflicting dependencies:\n\t{}'
                                               .format('\n\t'.join(conflicting_dependencies)))
    jar_attributes = global_dep_attributes.pop()

    excludes = set()
    for jar in jars:
      excludes.update(jar.excludes)

    any_have_url = False

    artifacts = OrderedDict()
    for jar in jars:
      ext = jar.ext
      url = jar.get_url()
      if url:
        any_have_url = True
      classifier = jar.classifier
      artifact = Artifact(name=jar.name,
                          type_=ext or 'jar',
                          ext=ext,
                          url=url,
                          classifier=classifier)
      artifacts[(ext, url, classifier)] = artifact

    template = TemplateData(
        org=jar_attributes.org,
        module=jar_attributes.name,
        version=jar_attributes.rev,
        mutable=jar_attributes.mutable,
        force=jar_attributes.force,
        transitive=jar_attributes.transitive,
        artifacts=artifacts.values(),
        any_have_url=any_have_url,
        excludes=[cls._generate_exclude_template(exclude) for exclude in excludes])

    return template

  @classmethod
  def _generate_fetch_jar_template(cls, jars):
    global_dep_attributes = set(Dependency(org=jar.org,
                                           name=jar.name,
                                           rev=jar.rev,
                                           transitive=False,
                                           mutable=jar.mutable,
                                           force=True)
                                for jar in jars)
    if len(global_dep_attributes) != 1:
      # If we batch fetches and assume conflict manager all, we could ignore these.
      # Leaving this here for now.
      conflicting_dependencies = sorted(str(g) for g in global_dep_attributes)
      raise cls.IvyResolveConflictingDepsError('Found conflicting dependencies:\n\t{}'
                                               .format('\n\t'.join(conflicting_dependencies)))
    jar_attributes = global_dep_attributes.pop()

    any_have_url = False

    artifacts = OrderedDict()
    for jar in jars:
      ext = jar.ext
      url = jar.get_url()
      if url:
        any_have_url = True
      classifier = jar.classifier
      artifact = Artifact(name=jar.name,
                          type_=ext or 'jar',
                          ext=ext,
                          url=url,
                          classifier=classifier)
      artifacts[(ext, url, classifier)] = artifact

    template = TemplateData(
        org=jar_attributes.org,
        module=jar_attributes.name,
        version=jar_attributes.rev,
        mutable=jar_attributes.mutable,
        artifacts=artifacts.values(),
        any_have_url=any_have_url,
        excludes=[])

    return template
