# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import re
from collections import defaultdict
from textwrap import dedent

from pants.backend.jvm.jar_dependency_utils import M2Coordinate
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.managed_jar_dependencies import ManagedJarDependencies
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.revision import Revision
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.subsystem.subsystem import Subsystem
from pants.task.task import Task


logger = logging.getLogger(__name__)


class JarDependencyManagement(Subsystem):
  """Used to keep track of pinning of external artifact versions.

  See the original design doc for this here:

  https://docs.google.com/document/d/1AM_0e1Az_NHtR150Zsuyaa6u7InzBQGLq8MrUT57Od8/edit
  """

  options_scope = 'jar-dependency-management'

  class IncompatibleManagedJarDependencies(TaskError):
    """The given set of targets has an incompatible combination of managed_jar_dependencies."""

  class DirectManagedVersionConflict(TaskError):
    """A directly declared jar_library conflicts with artifact versions in managed_jar_dependencies.
    """

  @classmethod
  def register_options(cls, register):
    super(JarDependencyManagement, cls).register_options(register)

    conflict_strategies = [
      'FAIL',
      'USE_DIRECT',
      'USE_DIRECT_IF_FORCED',
      'USE_MANAGED',
      'USE_NEWER',
    ]

    register('--default-target', advanced=True, type=str, default=None, fingerprint=True,
             help='Address of the default managed_jar_dependencies target to use for the whole '
                  'repo.')
    register('--conflict-strategy', choices=conflict_strategies, default='FAIL', fingerprint=True,
             help='Specifies how to behave when a jar_library has a jar with an explicit version '
                  'that differs from one in the managed_jar_dependencies target it depends on.')
    register('--suppress-conflict-warnings', action='store_true', default=False,
             help='Turns warning messages into debug messages when resolving jar conflicts.')

  def __init__(self, *args, **kwargs):
    super(JarDependencyManagement, self).__init__(*args, **kwargs)
    self._default_target = None
    # Map of ManagedJarDependencies target ids to PinnedJarArtifactSets.
    # Populated early in the build by the JarDependencyManagementSetup task.
    self._artifact_set_map = {}

  def resolve_version_conflict(self, managed_coord, direct_coord, force=False):
    """Resolves an artifact version conflict between directly specified and managed jars.

    This uses the user-defined --conflict-strategy to pick the appropriate artifact version (or to
    raise an error).

    This assumes the two conflict coordinates differ only by their version.

    :param M2Coordinate managed_coord: the artifact coordinate as defined by a
      managed_jar_dependencies object.
    :param M2Coordinate direct_coord: the artifact coordinate as defined by a jar_library target.
    :param bool force: Whether the artifact defined by the jar_library() was marked with force=True.
      This is checked only if one of the *_IF_FORCED conflict strategies is being used.
    :return: the coordinate of the artifact that should be resolved.
    :rtype: M2Coordinate
    :raises: JarDependencyManagement.DirectManagedVersionConflict if the versions are different and
      the --conflict-strategy is 'FAIL' (which is the default).
    """
    if M2Coordinate.unversioned(managed_coord) != M2Coordinate.unversioned(direct_coord):
      raise ValueError('Illegal arguments passed to resolve_version_conflict: managed_coord and '
                       'direct_coord must only differ by their version!\n'
                       '  Managed: {}\n  Direct:  {}\n'.format(
        M2Coordinate.unversioned(managed_coord),
        M2Coordinate.unversioned(direct_coord),
      ))

    if direct_coord.rev is None or direct_coord.rev == managed_coord.rev:
      return managed_coord

    strategy = self.get_options().conflict_strategy
    message = dedent("""
      An artifact directly specified by a jar_library target has a different version than what
      is specified by managed_jar_dependencies.

        Artifact: jar(org={org}, name={name}, classifier={classifier}, ext={ext})
        Direct version:  {direct}
        Managed version: {managed}
    """).format(
      org=direct_coord.org,
      name=direct_coord.name,
      classifier=direct_coord.classifier,
      ext=direct_coord.ext,
      direct=direct_coord.rev,
      managed=managed_coord.rev,
    )

    if strategy == 'FAIL':
      raise self.DirectManagedVersionConflict(
        '{}\nThis raises an error due to the current --jar-dependency-management-conflict-strategy.'
        .format(message)
      )

    is_silent = self.get_options().suppress_conflict_warnings
    log = logger.debug if is_silent else logger.warn

    if strategy == 'USE_DIRECT':
      log(message)
      log('[{}] Using direct version: {}'.format(strategy, direct_coord))
      return direct_coord

    if strategy == 'USE_DIRECT_IF_FORCED':
      log(message)
      if force:
        log('[{}] Using direct version, because force=True: {}'.format(strategy, direct_coord))
        return direct_coord
      else:
        log('[{}] Using managed version, because force=False: {}'.format(strategy, managed_coord))
        return managed_coord

    if strategy == 'USE_MANAGED':
      log(message)
      log('[{}] Using managed version: {}'.format(strategy, managed_coord))
      return managed_coord

    if strategy == 'USE_NEWER':
      newer = max([managed_coord, direct_coord],
                  key=lambda coord: Revision.lenient(coord.rev))
      log(message)
      log('[{}] Using newer version: {}'.format(strategy, newer))
      return newer

    raise TaskError('Unknown value for --conflict-strategy: {}'.format(strategy))

  @property
  def default_artifact_set(self):
    """The default set of pinned artifacts (ie from the --default-target).

    This will be None if --default-target is not set.
    """
    if not self._default_target:
      return None
    return self._artifact_set_map[self._default_target.id]

  def targets_by_artifact_set(self, targets):
    """Partitions the input targets by the sets of pinned artifacts they are managed by.

    :param list targets: the input targets (typically just JarLibrary targets).
    :return: a mapping of PinnedJarArtifactSet -> list of targets.
    :rtype: dict
    """
    sets_to_targets = defaultdict(list)
    for target in targets:
      sets_to_targets[self.for_target(target)].append(target)
    return dict(sets_to_targets)

  def for_targets(self, targets):
    """Attempts to find a single PinnedJarArtifactSet that works for all input targets.

    This just partitions the targets using the targets_by_artifact_set partitioning logic, and
    returns the key that works for all targets (ie the only key in the resulting map).

    Returns None if the resulting map has no entries, and raises an error if it has more than one.

    :param list targets: the input targets.
    :return: the single PinnedJarArtifactSet that works for everything, or None.
    :rtype: PinnedJarArtifactSet
    :raises: JarDependencyManagement.IncompatibleManagedJarDependencies
    """
    # TODO(gmalmquist): Remove this method once we properly run multiple ivy resolves for different
    # sets of pinned artifacts.
    sets_to_targets = self.targets_by_artifact_set(targets)
    sets = [artifact_set for artifact_set in sets_to_targets
            if any(isinstance(target, JarLibrary) for target in sets_to_targets[artifact_set])]
    if not sets:
      return None
    if len(sets) == 1:
      return next(iter(sets))
    raise self.IncompatibleManagedJarDependencies(
      'Targets use multiple incompatible managed_jar_dependencies: {}'
      .format(', '.join(map(str, sets)))
    )

  def for_target(self, target):
    """Computes and returns the PinnedJarArtifactSet that should be used to manage the given target.

    This returns None if the target is not a JarLibrary.

    :param Target target: The jar_library for which to find the managed_jar_dependencies object.
    :return: The the artifact set of the managed_jar_dependencies object for the target, or the
      default artifact set from --default-target.
    :rtype: PinnedJarArtifactSet
    """
    if not isinstance(target, JarLibrary):
      return None
    found_target = target.managed_dependencies
    if not found_target:
      return self.default_artifact_set
    return self._artifact_set_map[found_target.id]


class PinnedJarArtifactSet(object):
  """A set of artifact coordinates and what versions they should be pinned to."""

  class MissingVersion(TaskError):
    """This occurs if you try to insert an artifact without a version."""

  def __init__(self, pinned_coordinates=None):
    """
    :param pinned_coordinates: An optional list of coordinates to initialize the set with.
    """
    self._artifacts_to_versions = {}
    self._id = None
    if pinned_coordinates:
      for artifact in pinned_coordinates:
        self.put(artifact)

  _key = M2Coordinate.unversioned

  @property
  def id(self):
    """A unique, stable, hashable id over the set of pinned artifacts."""
    if not self._id:
      # NB(gmalmquist): This id is not cheap to compute if there are a large number of artifacts.
      # We cache it here, but invalidate the cached value if an artifact gets added or changed.
      self._id = tuple(sorted(map(str, self)))
    return self._id

  def put(self, artifact):
    """Adds the given coordinate to the set, using its version to pin it.

    If this set already contains an artifact with the same coordinates other than the version, it is
    replaced by the new artifact.

    :param M2Coordinate artifact: the artifact coordinate.
    """
    artifact = M2Coordinate.create(artifact)
    if artifact.rev is None:
      raise self.MissingVersion('Cannot pin an artifact to version "None"! {}'.format(artifact))
    key = self._key(artifact)
    previous = self._artifacts_to_versions.get(key)
    self._artifacts_to_versions[key] = artifact
    if previous != artifact:
      self._id = None

  def get(self, artifact):
    """Gets the coordinate with the correct version for the given artifact coordinate.

    :param M2Coordinate artifact: the coordinate to lookup.
    :return: a coordinate which is the same as the input, but with the correct pinned version. If
      this artifact set does not pin a version for the input artifact, this just returns the
      original coordinate.
    :rtype: M2Coordinate
    """
    coord = self._key(artifact)
    if coord in self._artifacts_to_versions:
      return self._artifacts_to_versions[coord]
    return artifact

  def __iter__(self):
    return iter(self._artifacts_to_versions.values())

  def __len__(self):
    return len(self._artifacts_to_versions)

  def __nonzero__(self):
    return len(self) > 0

  def __contains__(self, artifact):
    return self._key(artifact) in self._artifacts_to_versions

  def __getitem__(self, artifact):
    return self.get(artifact)

  def __hash__(self):
    return hash(self.id)

  def __eq__(self, other):
    return self.id == other.id

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return 'PinnedJarArtifactSet({})'.format(', '.join(self.id))

  def __str__(self):
    if len(self) == 0:
      return 'PinnedJarArtifactSet()'
    first = next(iter(self))
    if len(self) == 1:
      return 'PinnedJarArtifactSet({})'.format(first)
    return 'PinnedJarArtifactSet({}, ... {} artifacts)'.format(first, len(self)-1)


class JarDependencyManagementSetup(Task):
  """Initialize and validate the JarDependencyManagement subsystem."""

  class InvalidDefaultTarget(TaskError):
    """The default managed_jar_dependencies target is of the wrong type."""

  class DuplicateCoordinateError(TargetDefinitionException):
    """There were two identical jar entries other than the coordinate."""

    def __init__(self, target, coord, rev1, rev2):
      super(JarDependencyManagementSetup.DuplicateCoordinateError, self).__init__(
        target,
        'Version conflict inside a managed_jar_dependencies target: {coord} {rev1} vs {rev2}'
        .format(
          coord=coord,
          rev1=rev1,
          rev2=rev2,
        )
      )

  class MissingVersion(TargetDefinitionException):
    """A jar used to construct a managed_jar_dependencies artifact set is missing a version."""

    def __init__(self, target, coord):
      super(JarDependencyManagementSetup.MissingVersion, self).__init__(
        target,
        'The jar {} specified in {} is missing a version (rev).'.format(coord, target.address.spec)
      )

  @classmethod
  def global_subsystems(cls):
    return (JarDependencyManagement,)

  def execute(self):
    self._resolve_default_target()
    targets = self.context.targets(predicate=lambda t: isinstance(t, ManagedJarDependencies))
    self._compute_artifact_sets(targets)
    self._validate_managed_jar_dependencies_targets(targets)

  def _validate_managed_jar_dependencies_targets(self, targets):
    for target in targets:
      if target.dependencies:
        # TODO(gmalmquist): Remove this when we handle merging of transitive
        # managed_jar_dependencies.
        self.context.warn('{}: Chaining managed_jar_dependencies objects is not yet supported.'
                          .format(target.address.spec))

  def _resolve_default_target(self):
    manager = JarDependencyManagement.global_instance()
    spec = manager.get_options().default_target
    if not spec:
      return
    try:
      targets = list(self.context.resolve(spec))
    except AddressLookupError:
      raise self.InvalidDefaultTarget(
        'Unable to resolve default managed_jar_dependencies target: {}'.format(spec))
    target = targets[0]
    if not isinstance(target, ManagedJarDependencies):
      raise self.InvalidDefaultTarget(
        'Default managed_jar_dependencies target is an invalid target type: "{}" is a {}.'
        .format(spec, type(target).__name__))
    manager._artifact_set_map[target.id] = self._compute_artifact_set(target)
    manager._default_target = target

  def _compute_artifact_sets(self, targets):
    dm = JarDependencyManagement.global_instance()
    for target in targets:
      dm._artifact_set_map[target.id] = self._compute_artifact_set(target)
      self.context.log.debug('Computed artifact map for {} ({} jars)'
                             .format(target.id, dm._artifact_set_map[target.id]))

  def _library_targets(self, managed_jar_dependencies):
    for spec in managed_jar_dependencies.library_specs:
      for target in self.context.resolve(spec):
        yield target # NB(gmalmquist): I don't think this needs to be transitive.

  def _jar_iterator(self, managed_jar_dependencies):
    for jar in managed_jar_dependencies.payload.artifacts:
      yield jar
    for dep in self._library_targets(managed_jar_dependencies):
      if isinstance(dep, JarLibrary):
        for jar in dep.jar_dependencies:
          yield jar
      else:
        raise TargetDefinitionException(managed_jar_dependencies,
                                        'Artifacts must be jar() objects or the addresses of '
                                        'jar_library objects.')

  def _compute_artifact_set(self, managed_jar_dependencies):
    # TODO(gmalmquist): Extend this to be the union of any pinned artifacts from transitive
    # dependencies of this managed_jar_dependencies object. If there are conflicts between the versions
    # specified by parents and children, the children should win.
    artifact_set = PinnedJarArtifactSet()
    for jar in self._jar_iterator(managed_jar_dependencies):
      if jar.rev is None:
        raise self.MissingVersion(managed_jar_dependencies, jar)
      if jar in artifact_set and artifact_set[jar].rev != jar.rev:
        raise self.DuplicateCoordinateError(managed_jar_dependencies, jar, artifact_set[jar].rev,
                                            jar.rev)
      artifact_set.put(jar)
    return artifact_set
