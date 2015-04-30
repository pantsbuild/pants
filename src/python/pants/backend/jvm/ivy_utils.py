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
import xml
from collections import OrderedDict, defaultdict, namedtuple
from contextlib import contextmanager

from twitter.common.collections import OrderedSet, maybe_list

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.revision import Revision
from pants.base.target import Target
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.dirutil import safe_mkdir, safe_open


IvyArtifact = namedtuple('IvyArtifact', ['path', 'classifier'])
IvyModule = namedtuple('IvyModule', ['ref', 'artifacts', 'callers'])


logger = logging.getLogger(__name__)


class IvyModuleRef(object):
  def __init__(self, org, name, rev):
    self.org = org
    self.name = name
    self.rev = rev

  def __eq__(self, other):
    return self.org == other.org and self.name == other.name and self.rev == other.rev

  def __hash__(self):
    return hash((self.org, self.name, self.rev))

  @property
  def unversioned(self):
    """This returns an identifier for an IvyModuleRef without version information.

       It's useful because ivy might return information about a
       different version of a dependency than the one we request, and we
       want to ensure that all requesters of any version of that
       dependency are able to learn about it.
    """

    # latest.integration is ivy magic meaning "just get the latest version"
    return IvyModuleRef(name=self.name, org=self.org, rev='latest.integration')

class IvyInfo(object):
  def __init__(self):
    self.modules_by_ref = {}  # Map from ref to referenced module.
    # Map from ref of caller to refs of modules required by that caller.
    self._deps_by_caller = defaultdict(OrderedSet)
    # Map from _unversioned_ ref to OrderedSet of IvyArtifact instances.
    self._artifacts_by_ref = defaultdict(OrderedSet)

  def add_module(self, module):
    self.modules_by_ref[module.ref] = module
    if not module.artifacts:
      # Module was evicted, so do not record information about it
      return
    for caller in module.callers:
      self._deps_by_caller[caller.unversioned].add(module.ref)
    self._artifacts_by_ref[module.ref.unversioned].update(module.artifacts)

  def traverse_dependency_graph(self, ref, collector, memo=None, visited=None):
    """Traverses module graph, starting with ref, collecting values for each ref into the sets
    created by the collector function.

    :param ref an IvyModuleRef to start traversing the ivy dependency graph
    :param collector a function that takes a ref and returns a new set of values to collect for that ref,
           which will also be updated with all the dependencies accumulated values
    :param memo is a dict of ref -> set that memoizes the results of each node in the graph.
           If provided, allows for retaining cache across calls.
    :returns the accumulated set for ref
    """

    if memo is None:
      memo = dict()

    memoized_value = memo.get(ref)
    if memoized_value:
      return memoized_value

    visited = visited or set()
    if ref in visited:
      # Ivy allows for circular dependencies
      # If we're here, that means we're resolving something that
      # transitively depends on itself
      return set()
    visited.add(ref)

    acc = collector(ref)
    for dep in self._deps_by_caller.get(ref.unversioned, ()):
      acc.update(self.traverse_dependency_graph(dep, collector, memo, visited))
    memo[ref] = acc
    return acc

  def get_artifacts_for_jar_library(self, jar_library, memo=None):
    """Collects IvyArtifact instances for the passed jar_library.

    Because artifacts are only fetched for the "winning" version of a module, the artifacts
    will not always represent the version originally declared by the library.

    This method is transitive within the library's jar_dependencies, but will NOT
    walk into its non-jar dependencies.

    :param jar_library A JarLibrary to collect the transitive artifacts for.
    :param memo see `traverse_dependency_graph`
    """
    artifacts = OrderedSet()
    def create_collection(dep):
      return OrderedSet([dep])
    for jar in jar_library.jar_dependencies:
      jar_module_ref = IvyModuleRef(jar.org, jar.name, jar.rev)
      valid_classifiers = jar.artifact_classifiers
      artifacts_for_jar = []
      for module_ref in self.traverse_dependency_graph(jar_module_ref, create_collection, memo):
        artifacts_for_jar.extend(
          artifact for artifact in self._artifacts_by_ref[module_ref.unversioned]
          if artifact.classifier in valid_classifiers
        )

      artifacts.update(artifacts_for_jar)
    return artifacts

  def get_jars_for_ivy_module(self, jar, memo=None):
    """Collects dependency references of the passed jar
    :param jar an IvyModuleRef for a third party dependency.
    :param memo see `traverse_dependency_graph`
    """

    ref = IvyModuleRef(jar.org, jar.name, jar.rev)
    def create_collection(dep):
      s = OrderedSet()
      if ref != dep:
        s.add(dep)
      return s
    return self.traverse_dependency_graph(ref, create_collection, memo)


class IvyUtils(object):
  """Useful methods related to interaction with ivy."""

  ivy_lock = threading.RLock()

  IVY_TEMPLATE_PACKAGE_NAME = __name__
  IVY_TEMPLATE_PATH = os.path.join('tasks', 'templates', 'ivy_resolve', 'ivy.mustache')

  class IvyResolveReportError(Exception):
    """Raised when the ivy report cannot be found."""
    pass

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
  def _find_new_symlinks(cls, existing_symlink_path, updated_symlink_path):
    """Find the difference between the existing and updated symlink path.

    :param existing_symlink_path: map from path : symlink
    :param updated_symlink_path: map from path : symlink after new resolve
    :return: the portion of updated_symlink_path that is not found in existing_symlink_path.
    """
    diff_map = OrderedDict()
    for key, value in updated_symlink_path.iteritems():
      if not key in existing_symlink_path:
        diff_map[key] = value
    return diff_map

  @classmethod
  def symlink_cachepath(cls, ivy_cache_dir, inpath, symlink_dir, outpath, existing_symlink_map):
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
    updated_symlink_map = OrderedDict()
    with safe_open(inpath, 'r') as infile:
      inpaths = filter(None, infile.read().strip().split(os.pathsep))
      paths = OrderedSet([os.path.realpath(path) for path in inpaths])

    for path in paths:
      if path.startswith(real_ivy_cache_dir):
        updated_symlink_map[path] = os.path.join(symlink_dir, os.path.relpath(path, real_ivy_cache_dir))
      else:
        # This path is outside the cache. We won't symlink it.
        updated_symlink_map[path] = path

    # Create symlinks for paths in the ivy cache dir that we haven't seen before.
    new_symlinks = cls._find_new_symlinks(existing_symlink_map, updated_symlink_map)

    for path, symlink in new_symlinks.iteritems():
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
      outfile.write(':'.join(OrderedSet(updated_symlink_map.values())))

    return dict(updated_symlink_map)

  @staticmethod
  def identify(targets):
    targets = list(targets)
    if len(targets) == 1 and targets[0].is_jvm and getattr(targets[0], 'provides', None):
      return targets[0].provides.org, targets[0].provides.name
    else:
      return 'internal', Target.maybe_readable_identify(targets)

  @classmethod
  def xml_report_path(cls, targets, conf):
    """The path to the xml report ivy creates after a retrieve."""
    org, name = cls.identify(targets)
    cachedir = IvySubsystem.global_instance().get_options().cache_dir
    return os.path.join(cachedir, '{}-{}-{}.xml'.format(org, name, conf))

  @classmethod
  def parse_xml_report(cls, targets, conf):
    """Parse the ivy xml report corresponding to the targets and conf passed.

    :param targets: Targets ivy considered during ivy_resolve()
    :type targets: list of Target
    :param string conf: the ivy conf name (e.g. "default")
    :return: The info in the xml report or None if target is empty.
    :rtype: IvyInfo
    :raises:  IvyResolveReportError if no report exists.
    """
    if not targets:
      return None

    path = cls.xml_report_path(targets, conf)
    if not os.path.exists(path):
      raise cls.IvyResolveReportError('Missing expected ivy output file {}'.format(path))

    return cls._parse_xml_report(path)

  @classmethod
  def _parse_xml_report(cls, path):
    if not os.path.exists(path):
      return None

    ret = IvyInfo()
    etree = xml.etree.ElementTree.parse(path)
    doc = etree.getroot()
    for module in doc.findall('dependencies/module'):
      org = module.get('organisation')
      name = module.get('name')
      for revision in module.findall('revision'):
        rev = revision.get('name')
        artifacts = []
        for artifact in revision.findall('artifacts/artifact'):
          artifacts.append(IvyArtifact(path=artifact.get('location'),
                                       classifier=artifact.get('extra-classifier')))
        callers = []
        for caller in revision.findall('caller'):
          callers.append(IvyModuleRef(caller.get('organisation'),
                                      caller.get('name'),
                                      caller.get('callerrev')))
        ret.add_module(IvyModule(IvyModuleRef(org, name, rev), artifacts, callers))
    return ret

  @classmethod
  def generate_ivy(cls, targets, jars, excludes, ivyxml, confs):
    org, name = cls.identify(targets)

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
    dependencies = [cls._generate_jar_template(jar, confs) for jar in jars]
    overrides = [cls._generate_override_template(dep) for dep in dependencies if dep.force]

    excludes = [cls._generate_exclude_template(exclude) for exclude in excludes]

    template_data = TemplateData(
        org=org,
        module=name,
        version='latest.integration',
        publications=None,
        configurations=maybe_list(confs), # Mustache doesn't like sets.
        dependencies=dependencies,
        excludes=excludes,
        overrides=overrides)

    safe_mkdir(os.path.dirname(ivyxml))
    with open(ivyxml, 'w') as output:
      generator = Generator(pkgutil.get_data(__name__, cls.IVY_TEMPLATE_PATH),
                            root_dir=get_buildroot(),
                            lib=template_data)
      generator.write(output)

  @classmethod
  def calculate_classpath(cls, targets):
    jars = OrderedDict()
    excludes = set()
    targets_processed = set()

    # Support the ivy force concept when we sanely can for internal dep conflicts.
    # TODO(John Sirois): Consider supporting / implementing the configured ivy revision picking
    # strategy generally.
    def add_jar(jar):
      coordinate = jar.coordinate_without_rev
      existing = jars.get(coordinate)
      jars[coordinate] = jar if not existing else (
        cls._resolve_conflict(existing=existing, proposed=jar)
      )

    def collect_jars(target):
      targets_processed.add(target)
      if isinstance(target, JarLibrary):
        for jar in target.jar_dependencies:
          if jar.rev:
            add_jar(jar)

      target_excludes = target.payload.get_field_value('excludes')
      if target_excludes:
        excludes.update(target_excludes)
      if target.is_exported:
        # if a source dep is exported, it should always override remote/binary versions
        # of itself, ie "round trip" dependencies
        excludes.add(Exclude(org=target.provides.org, name=target.provides.name))

    for target in targets:
      target.walk(collect_jars, predicate=lambda target: target not in targets_processed)

    return jars.values(), excludes

  @staticmethod
  def _resolve_conflict(existing, proposed):
    if proposed == existing:
      if proposed.force:
        return proposed
      return existing
    elif existing.force and proposed.force:
      raise TaskError('Cannot force {}#{};{} to both rev {} and {}'.format(
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
      try:
        if Revision.lenient(proposed.rev) > Revision.lenient(existing.rev):
          logger.debug('Upgrading {}#{};{} from rev {}  to {}'.format(
            proposed.org, proposed.name, proposed.classifier or '', existing.rev, proposed.rev,
          ))
          return proposed
        else:
          return existing
      except Revision.BadRevision as e:
        raise TaskError('Failed to parse jar revision', e)

  @staticmethod
  def _is_mutable(jar):
    if jar.mutable is not None:
      return jar.mutable
    return False

  @classmethod
  def _generate_jar_template(cls, jar, confs):
    template = TemplateData(
        org=jar.org,
        module=jar.name,
        version=jar.rev,
        mutable=cls._is_mutable(jar),
        force=jar.force,
        excludes=[cls._generate_exclude_template(exclude) for exclude in jar.excludes],
        transitive=jar.transitive,
        artifacts=jar.artifacts,
        configurations=maybe_list(confs))
    return template
