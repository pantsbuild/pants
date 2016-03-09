# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import logging
import os
import pkgutil
import threading
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict, namedtuple

import six
from twitter.common.collections import OrderedSet

from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.backend.jvm.subsystems.jar_dependency_management import (JarDependencyManagement,
                                                                    PinnedJarArtifactSet)
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.deprecated import deprecated
from pants.base.generator import Generator, TemplateData
from pants.base.revision import Revision
from pants.build_graph.target import Target
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.util import execute_runner
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir, safe_open
from pants.util.fileutil import atomic_copy
from pants.util.objects import datatype


IvyModule = namedtuple('IvyModule', ['ref', 'artifact', 'callers'])


Dependency = namedtuple('DependencyAttributes',
                        ['org', 'name', 'rev', 'mutable', 'force', 'transitive'])


Artifact = namedtuple('Artifact', ['name', 'type_', 'ext', 'url', 'classifier'])


logger = logging.getLogger(__name__)


class IvyResolveRequest(datatype('IvyResolveRequest', [
  'hash_name', 'confs', 'artifacts', 'pinned_artifacts', 'global_excludes', 'extra_args'])):
  """Contains all unique information identifying a particular ivy resolve.

  When deciding whether to add a property here or to add it to the `do_resolve` or
  `load_resolve` methods, ask whether it affects the identity of the resolve: if it
  does, it should be part of this datatype.

  :param hash_name: A unique string name for this resolve.
  :param confs: A tuple of string ivy confs to resolve for.
  :param artifacts: A tuple of "artifact-alikes" to fetch; ie, JarDependency objects.
  :param pinned_artifacts: A tuple of "artifact-alikes" to force the versions of.
  :param global_excludes: A tuple of Exclude objects to apply globally within this resolve.
  :param extra_args: Extra Ivy CLI arguments.
  """

  _FULL_RESOLVE_IVY_XML_FILE_NAME = 'ivy.xml'

  def symlink_classpath_filename(self, workdir):
    return os.path.join(workdir, 'classpath')

  def ivy_cache_classpath_filename(self, workdir):
    return self.symlink_classpath_filename(workdir) + '.raw'

  def _resolve_report_path(self, workdir, conf):
    return os.path.join(workdir, 'resolve-report-{}.xml'.format(conf))

  def ivy_xml_path(self, workdir):
    return os.path.join(workdir, self._FULL_RESOLVE_IVY_XML_FILE_NAME)

  def reports_by_conf(self, workdir):
    return {c: self._resolve_report_path(workdir, c) for c in self.confs}

  def result_files_exist(self, workdir):
    reports = self.reports_by_conf(workdir).values()
    return (all(os.path.isfile(report) for report in reports) and
            os.path.isfile(self.ivy_cache_classpath_filename(workdir)))


class IvyResolveResult(object):
  """The result of an Ivy resolution.

  The result data includes the list of resolved artifacts, the relationships between those artifacts
  and the targets that requested them and the hash name of the resolve.
  """

  def __init__(self, resolved_artifact_paths, symlink_map, resolve_hash_name, ivy_info_by_conf):
    self._ivy_info_by_conf = ivy_info_by_conf
    self.resolved_artifact_paths = resolved_artifact_paths
    self.resolve_hash_name = resolve_hash_name
    self._symlink_map = symlink_map

  @property
  def has_resolved_artifacts(self):
    """The requested targets have a resolution associated with them."""
    return self.resolve_hash_name is not None

  def all_linked_artifacts_exist(self):
    """All of the artifact paths for this resolve point to existing files."""
    for path in self.resolved_artifact_paths:
      if not os.path.isfile(path):
        return False
    else:
      return True

  def resolved_jars_for_each_target(self, conf, targets):
    """Yields the resolved jars for each passed JarLibrary.

    If there is no report for the requested conf, yields nothing.

    :param conf: The ivy conf to load jars for.
    :param targets: The collection of JarLibrary targets to find resolved jars for.
    :yield: target, resolved_jars
    :raises IvyTaskMixin.UnresolvedJarError
    """
    ivy_info = self._ivy_info_by_conf.get(conf, None)
    if not ivy_info:
      return

    jar_library_targets = [t for t in targets if isinstance(t, JarLibrary)]
    ivy_jar_memo = {}
    for target in jar_library_targets:
      # Add the artifacts from each dependency module.
      resolved_jars = self._resolved_jars_with_symlinks(conf, ivy_info, ivy_jar_memo,
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

  def _resolved_jars_with_symlinks(self, conf, ivy_info, ivy_jar_memo, coordinates, target):
    raw_resolved_jars = ivy_info.get_resolved_jars_for_coordinates(coordinates,
                                                                   memo=ivy_jar_memo)
    resolved_jars = [self._new_resolved_jar_with_symlink_path(conf, target, raw_resolved_jar)
                     for raw_resolved_jar in raw_resolved_jars]
    return resolved_jars


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
    :rtype: list of :class:`pants.backend.jvm.jar_dependency_utils.ResolvedJar`
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
      jar_module_ref = IvyModuleRef(jar.org, jar.name, jar.rev, classifier)
      for module_ref in self.traverse_dependency_graph(jar_module_ref, create_collection, memo):
        for artifact_path in self._artifacts_by_ref[module_ref.unversioned]:
          resolved_jars.add(to_resolved_jar(module_ref, artifact_path))
    return resolved_jars


class IvyUtils(object):
  """Useful methods related to interaction with ivy.

  :API: public
  """

  _ivy_lock = threading.RLock()

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
  @deprecated('0.0.80', hint_message='Use `do_resolve` and `load_resolve` instead.')
  def load_classpath_from_cachepath(path):
    return IvyUtils._load_classpath_from_cachepath(path)

  @staticmethod
  def _load_classpath_from_cachepath(path):
    if not os.path.exists(path):
      return []
    else:
      with safe_open(path, 'r') as cp:
        return filter(None, (path.strip() for path in cp.read().split(os.pathsep)))

  @classmethod
  def load_resolve(cls, cachedir, workdir, symlinkdir, request, symlink_lock=None, fatal=True):
    """Given a IvyResolveRequest, return an IvyResolveResult or None.

    If `fatal=True`, then rather than returning None, any failure to locate an input or output
    will raise a useful exception instead.

    :param cachedir: The global ivy cache directory.
    :param workdir: A unique working directory for the resolve.
    :param symlinkdir: A shared (probably) directory under which to create a symlink map. Protected
      by the (optional) symlink_lock.
    :param request: The IvyResolveRequest to execute.
    :param symlink_lock: An optional threading.Lock to protect access to the shared symlinkdir.
    :param fatal: If true, failures to load the resolve will throw an exception rather than
      returning None.
    :returns: An IvyResolveResult or None
    """
    if not request.result_files_exist(workdir):
      # Inputs not present.
      if fatal:
        raise IvyResolveMappingError(
            'Resolve report did not exist in {} for {}'.format(workdir, request))
      return None

    # Make our actual classpath be symlinks, so that the paths are uniform across systems.
    # Note that we must do this even if we read the raw_target_classpath_file from the artifact
    # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
    symlink_lock = symlink_lock if symlink_lock is not None else threading.Lock()
    with symlink_lock:
      symlink_map = cls._symlink_cachepath(cachedir,
                                           request.ivy_cache_classpath_filename(workdir),
                                           symlinkdir,
                                           request.symlink_classpath_filename(workdir))

    resolved_artifact_paths = \
      cls._load_classpath_from_cachepath(request.symlink_classpath_filename(workdir))

    # Parse reports and create a result.
    ivy_info_by_conf = {conf: IvyUtils.parse_xml_report(conf, report)
                       for conf, report in request.reports_by_conf(workdir).items()}
    result = IvyResolveResult(resolved_artifact_paths,
                              symlink_map,
                              request.hash_name,
                              ivy_info_by_conf)
    if not result.all_linked_artifacts_exist():
      # Outputs not present.
      if fatal:
        raise IvyResolveMappingError(
            'Some artifacts were not linked to {} for {}'.format(workdir, result))
      return None
    return result

  @classmethod
  def do_resolve(cls, ivy, executor, workdir, request, jvm_options=None, workunit_name=None, workunit_factory=None):
    """Execute the given IvyResolveRequest.

    :param ivy: An ivy.Ivy instance to use.
    :param executor: A JVM executor to use to invoke ivy.
    :param workdir: A working directory to write the resolve results into.
    :param request: An IvyResolveRequest.
    :param jvm_options: A list of jvm option strings to use for the ivy invoke, or None.
    :param workunit_name: A workunit name for the ivy invoke, or None.
    :param workunit_factory: A workunit factory for the ivy invoke, or None.
    """
    safe_mkdir(workdir)

    jvm_options = jvm_options or []
    workunit_name = workunit_name if workunit_name is not None else 'ivy'

    with safe_concurrent_creation(request.ivy_cache_classpath_filename(workdir)) as raw_target_classpath_file_tmp:
      args = ['-cachepath', raw_target_classpath_file_tmp] + request.extra_args

      ivyxml = request.ivy_xml_path(workdir)
      with cls._ivy_lock:
        cls._generate_ivy(request.artifacts, request.global_excludes, ivyxml, request.confs,
                          request.hash_name, request.pinned_artifacts)

        cls._exec_ivy(ivy, request.confs, ivyxml, args, jvm_options, executor, workunit_name, workunit_factory)

        # Copy ivy resolve file(s) into the workdir.
        for conf in request.confs:
          atomic_copy(cls.xml_report_path(ivy.ivy_cache_dir, request.hash_name, conf),
                      request._resolve_report_path(workdir, conf))

      if not os.path.exists(raw_target_classpath_file_tmp):
        raise IvyError('Ivy failed to create classpath file at {}'
                       .format(raw_target_classpath_file_tmp))

    logger.debug('Moved ivy classfile file to {dest}'.format(dest=request.ivy_cache_classpath_filename))

  @classmethod
  @deprecated('0.0.80', hint_message='Use `do_resolve` and `load_resolve` instead.')
  def exec_ivy(cls, ivy, confs, ivyxml, args,
               jvm_options,
               executor,
               workunit_name,
               workunit_factory):
    return cls._exec_ivy(ivy, confs, ivyxml, args, jvm_options, executor, workunit_name,
                         workunit_factory)

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
        raise IvyUtils.IvyError('Ivy returned {result}. cmd={cmd}'.format(result=result, cmd=runner.cmd))
    except runner.executor.Error as e:
      raise IvyUtils.IvyError(e)

  @classmethod
  @deprecated('0.0.80', hint_message='Use `do_resolve` and `load_resolve` instead.')
  def symlink_cachepath(cls, ivy_cache_dir, inpath, symlink_dir, outpath):
    return cls._symlink_cachepath(ivy_cache_dir, inpath, symlink_dir, outpath)

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

  @staticmethod
  @deprecated('0.0.80', hint_message='Use `do_resolve` and `load_resolve` instead.')
  def identify(targets):
    targets = list(targets)
    if len(targets) == 1 and targets[0].is_jvm and getattr(targets[0], 'provides', None):
      return targets[0].provides.org, targets[0].provides.name
    else:
      return IvyUtils.INTERNAL_ORG_NAME, Target.maybe_readable_identify(targets)

  @classmethod
  def xml_report_path(cls, cache_dir, resolve_hash_name, conf):
    """The path to the xml report ivy creates after a retrieve.

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
          ivy_module = IvyModule(ivy_module_ref, artifact_cache_path, callers)

          ret.add_module(ivy_module)
    return ret

  @classmethod
  @deprecated('0.0.80', hint_message='Use `do_resolve` and `load_resolve` instead.')
  def generate_ivy(cls, targets, jars, excludes, ivyxml, confs, resolve_hash_name=None,
                   pinned_artifacts=None):
    if not resolve_hash_name:
      resolve_hash_name = Target.maybe_readable_identify(targets)
    return cls._generate_ivy(jars, excludes, ivyxml, confs, resolve_hash_name, pinned_artifacts)

  @classmethod
  def _generate_ivy(cls, jars, excludes, ivyxml, confs, resolve_hash_name, pinned_artifacts=None):
    org = IvyUtils.INTERNAL_ORG_NAME
    name = resolve_hash_name

    extra_configurations = [conf for conf in confs if conf and conf != 'default']

    jars_by_key = OrderedDict()
    for jar in jars:
      jars = jars_by_key.setdefault((jar.org, jar.name), [])
      jars.append(jar)

    manager = JarDependencyManagement.global_instance()
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
    overrides = [cls._generate_override_template(coord) for coord in artifact_set]

    excludes = [cls._generate_exclude_template(exclude) for exclude in excludes]

    template_data = TemplateData(
        org=org,
        module=name,
        extra_configurations=extra_configurations,
        dependencies=dependencies,
        excludes=excludes,
        overrides=overrides)

    template_relpath = os.path.join('templates', 'ivy_utils', 'ivy.mustache')
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
      if not target.is_exported:
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
      jars = {coordinate: jar.copy(excludes=jar.excludes + additional_excludes)
              for coordinate, jar in jars.items()}

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
      url = jar.url
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
