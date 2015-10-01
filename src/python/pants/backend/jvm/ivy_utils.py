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
from contextlib import contextmanager

import six
from twitter.common.collections import OrderedSet

from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.build_environment import get_buildroot
from pants.base.generator import Generator, TemplateData
from pants.base.revision import Revision
from pants.build_graph.target import Target
from pants.util.dirutil import safe_mkdir, safe_open


IvyModule = namedtuple('IvyModule', ['ref', 'artifact', 'callers'])


logger = logging.getLogger(__name__)


class IvyResolveMappingError(Exception):
  """Raised when there is a failure mapping the ivy resolve results to pants objects."""


class IvyModuleRef(object):

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
    for dep in self._deps_by_caller.get(ref.caller_key, ()):
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

  def get_resolved_jars_for_jar_library(self, jar_library, memo=None):
    """Collects jars for the passed jar_library.

    Because artifacts are only fetched for the "winning" version of a module, the artifacts
    will not always represent the version originally declared by the library.

    This method is transitive within the library's jar_dependencies, but will NOT
    walk into its non-jar dependencies.

    :param jar_library A JarLibrary to collect the transitive artifacts for.
    :param memo see `traverse_dependency_graph`
    :returns: all the artifacts for all of the jars in this library, including transitive deps
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
    for jar in jar_library.jar_dependencies:
      classifier = jar.classifier if self._conf == 'default' else self._conf
      jar_module_ref = IvyModuleRef(jar.org, jar.name, jar.rev, classifier)
      for module_ref in self.traverse_dependency_graph(jar_module_ref, create_collection, memo):
        for artifact_path in self._artifacts_by_ref[module_ref.unversioned]:
          resolved_jars.add(to_resolved_jar(module_ref, artifact_path))
    return resolved_jars


class IvyUtils(object):
  """Useful methods related to interaction with ivy."""

  ivy_lock = threading.RLock()

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
    return TemplateData(org=jar.org, module=jar.module, version=jar.version)

  @staticmethod
  @contextmanager
  def cachepath(path):
    if not os.path.exists(path):
      yield ()
    else:
      with safe_open(path, 'r') as cp:
        yield (path.strip() for path in cp.read().split(os.pathsep) if path.strip())

  @classmethod
  def symlink_cachepath(cls, ivy_cache_dir, inpath, symlink_dir, outpath):
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
    with safe_open(inpath, 'r') as infile:
      inpaths = filter(None, infile.read().strip().split(os.pathsep))
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
  def parse_xml_report(cls, cache_dir, resolve_hash_name, conf):
    """Parse the ivy xml report corresponding to the name passed to ivy.

    :param string cache_dir: The path of the ivy cache dir used for resolves.
    :param string resolve_hash_name: Hash from the Cache key from the VersionedTargetSet used for
                                     resolution; if `None` returns `None` instead of attempting to
                                     parse any report.
    :param string conf: the ivy conf name (e.g. "default")
    :returns: The info in the xml report or None if target is empty.
    :rtype: :class:`IvyInfo`
    :raises: :class:`IvyResolveMappingError` if no report exists.
    """
    # TODO(John Sirois): Cleanup acceptance of None, this is IvyResolve's concern, not ours.
    if not resolve_hash_name:
      return None
    path = cls.xml_report_path(cache_dir, resolve_hash_name, conf)
    if not os.path.exists(path):
      raise cls.IvyResolveReportError('Missing expected ivy output file {}'.format(path))

    return cls._parse_xml_report(conf, path)

  @classmethod
  def _parse_xml_report(cls, conf, path):
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
  def generate_ivy(cls, targets, jars, excludes, ivyxml, confs, resolve_hash_name=None):
    if resolve_hash_name:
      org = IvyUtils.INTERNAL_ORG_NAME
      name = resolve_hash_name
    else:
      org, name = cls.identify(targets)

    extra_configurations = [conf for conf in confs if conf and conf != 'default']

    jars_by_key = OrderedDict()
    for jar in jars:
      jars = jars_by_key.setdefault((jar.org, jar.name), [])
      jars.append(jar)

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
    overrides = [cls._generate_override_template(dep) for dep in dependencies if dep.force]

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
  def calculate_classpath(cls, targets, gather_excludes=True):
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
      if gather_excludes:
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
      for coordinate, jar in jars.items():
        jar.excludes += additional_excludes

    return jars.values(), global_excludes

  @classmethod
  def _resolve_conflict(cls, existing, proposed):
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
    Dependency = namedtuple('DependencyAttributes', ['org', 'name', 'rev', 'mutable', 'force',
                                                     'transitive'])
    global_dep_attributes = set(Dependency(org=jar.org,
                                           name=jar.name,
                                           rev=jar.rev,
                                           mutable=jar.mutable,
                                           force=jar.force,
                                           transitive=jar.transitive)
                                for jar in jars)
    if len(global_dep_attributes) != 1:
      # TODO(John Sirois): Need to provide information about where these came from - could be
      # far-flung JarLibrary targets.  The jars here were collected from targets via
      # `calculate_classpath` above and so merging of the 2 could provide the context needed.
      # See: https://github.com/pantsbuild/pants/issues/2239
      conflicting_dependencies = sorted(str(g) for g in global_dep_attributes)
      raise cls.IvyResolveConflictingDepsError('Found conflicting dependencies:\n\t{}'
                                               .format('\n\t'.join(conflicting_dependencies)))
    jar_attributes = global_dep_attributes.pop()

    excludes = set()
    for jar in jars:
      excludes.update(jar.excludes)

    Artifact = namedtuple('Artifact', ['name', 'type_', 'ext', 'url', 'classifier'])
    artifacts = OrderedDict()
    for jar in jars:
      ext = jar.ext
      url = jar.url
      classifier = jar.classifier
      artifact = Artifact(name=jar.name,
                          type_=ext or 'jar',
                          ext=ext,
                          url=url,
                          classifier=classifier)
      artifacts[(ext, url, classifier)] = artifact

    if len(artifacts) == 1:
      # If the only artifact has no attributes that we need a nested <artifact/> for, just emit
      # a <dependency/>.
      artifacts.pop((None, None, None), None)

    template = TemplateData(
        org=jar_attributes.org,
        module=jar_attributes.name,
        version=jar_attributes.rev,
        mutable=jar_attributes.mutable,
        force=jar_attributes.force,
        transitive=jar_attributes.transitive,
        artifacts=artifacts.values(),
        excludes=[cls._generate_exclude_template(exclude) for exclude in excludes])

    return template
