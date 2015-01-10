# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict, namedtuple
from contextlib import contextmanager
import errno
import os
import pkgutil
import threading
import xml

from twitter.common.collections import OrderedDict, OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.revision import Revision
from pants.base.target import Target
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy import Ivy
from pants.java import util
from pants.util.dirutil import safe_mkdir, safe_open


IvyModuleRef = namedtuple('IvyModuleRef', ['org', 'name', 'rev'])
IvyArtifact = namedtuple('IvyArtifact', ['path', 'classifier'])
IvyModule = namedtuple('IvyModule', ['ref', 'artifacts', 'callers'])


class IvyInfo(object):
  def __init__(self):
    self.modules_by_ref = {}  # Map from ref to referenced module.
    # Map from ref of caller to refs of modules required by that caller.
    self._deps_by_caller = defaultdict(OrderedSet)

  def add_module(self, module):
    self.modules_by_ref[module.ref] = module
    for caller in module.callers:
      self._deps_by_caller[caller].add(module.ref)

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
    for dep in self._deps_by_caller.get(ref, ()):
      acc.update(self.traverse_dependency_graph(dep, collector, memo, visited))
    memo[ref] = acc
    return acc

  def get_jars_for_ivy_module(self, jar, memo=None):
    """Collects dependency references of the passed jar
    :param jar an IvyModuleRef for a third party dependency.
    :param memo a dict of ref -> set that memoizes dependencies for each ref as they are resolved.
    """

    ref = jar
    def create_collection(dep):
      s = OrderedSet()
      if ref != dep:
        s.add(dep)
      return s
    return self.traverse_dependency_graph(jar, create_collection, memo)


class IvyUtils(object):
  """Useful methods related to interaction with ivy."""

  IVY_TEMPLATE_PACKAGE_NAME = __name__
  IVY_TEMPLATE_PATH = os.path.join('tasks', 'templates', 'ivy_resolve', 'ivy.mustache')

  def __init__(self, config, log):
    self._log = log

    self._transitive = config.getbool('ivy-resolve', 'transitive', default=True)
    self._args = config.getlist('ivy-resolve', 'args', default=[])
    self._jvm_options = config.getlist('ivy-resolve', 'jvm_args', default=[])
    # Disable cache in File.getCanonicalPath(), makes Ivy work with -symlink option properly on ng.
    self._jvm_options.append('-Dsun.io.useCanonCaches=false')
    self._workdir = os.path.join(config.getdefault('pants_workdir'), 'ivy')
    self._template_path = self.IVY_TEMPLATE_PATH

  @staticmethod
  def _generate_exclude_template(exclude):
    return TemplateData(org=exclude.org, name=exclude.name)

  @staticmethod
  def _generate_override_template(jar):
    return TemplateData(org=jar.org, module=jar.module, version=jar.version)

  @staticmethod
  def is_classpath_artifact(path):
    """Subclasses can override to determine whether a given artifact represents a classpath
    artifact."""
    return path.endswith('.jar') or path.endswith('.war')

  @classmethod
  def is_mappable_artifact(cls, org, name, path):
    """Subclasses can override to determine whether a given artifact represents a mappable
    artifact."""
    return cls.is_classpath_artifact(path)

  @staticmethod
  @contextmanager
  def cachepath(path):
    if not os.path.exists(path):
      yield ()
    else:
      with safe_open(path, 'r') as cp:
        yield (path.strip() for path in cp.read().split(os.pathsep) if path.strip())

  @staticmethod
  def symlink_cachepath(ivy_cache_dir, inpath, symlink_dir, outpath):
    """Symlinks all paths listed in inpath that are under ivy_cache_dir into symlink_dir.

    Preserves all other paths. Writes the resulting paths to outpath.
    Returns a map of path -> symlink to that path.
    """
    safe_mkdir(symlink_dir)
    with safe_open(inpath, 'r') as infile:
      paths = filter(None, infile.read().strip().split(os.pathsep))
    new_paths = []
    for path in paths:
      if not path.startswith(ivy_cache_dir):
        new_paths.append(path)
        continue
      symlink = os.path.join(symlink_dir, os.path.relpath(path, ivy_cache_dir))
      try:
        os.makedirs(os.path.dirname(symlink))
      except OSError as e:
        if e.errno != errno.EEXIST:
          raise
      # Note: The try blocks cannot be combined. It may be that the dir exists but the link doesn't.
      try:
        os.symlink(path, symlink)
      except OSError as e:
        # We don't delete and recreate the symlink, as this may break concurrently executing code.
        if e.errno != errno.EEXIST:
          raise
      new_paths.append(symlink)
    with safe_open(outpath, 'w') as outfile:
      outfile.write(':'.join(new_paths))
    symlink_map = dict(zip(paths, new_paths))
    return symlink_map

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
    cachedir = Bootstrapper.instance().ivy_cache_dir
    return os.path.join(cachedir, '%s-%s-%s.xml' % (org, name, conf))

  @classmethod
  def parse_xml_report(cls, targets, conf):
    """Returns the IvyInfo representing the info in the xml report, or None if no report exists."""
    path = cls.xml_report_path(targets, conf)
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

  def _extract_classpathdeps(self, targets):
    """Subclasses can override to filter out a set of targets that should be resolved for classpath
    dependencies.
    """
    def is_classpath(target):
      return (target.is_jar or
              target.is_internal and any(jar for jar in target.jar_dependencies if jar.rev))

    classpath_deps = OrderedSet()
    for target in targets:
      classpath_deps.update(t for t in target.resolve() if t.is_concrete and is_classpath(t))
    return classpath_deps

  def _generate_ivy(self, targets, jars, excludes, ivyxml, confs):
    org, name = self.identify(targets)

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
    dependencies = [self._generate_jar_template(jar, confs) for jar in jars]
    overrides = [self._generate_override_template(dep) for dep in dependencies if dep.force]

    excludes = [self._generate_exclude_template(exclude) for exclude in excludes]

    template_data = TemplateData(
        org=org,
        module=name,
        version='latest.integration',
        publications=None,
        configurations=confs,
        dependencies=dependencies,
        excludes=excludes,
        overrides=overrides)

    safe_mkdir(os.path.dirname(ivyxml))
    with open(ivyxml, 'w') as output:
      generator = Generator(pkgutil.get_data(__name__, self._template_path),
                            root_dir=get_buildroot(),
                            lib=template_data)
      generator.write(output)

  def _calculate_classpath(self, targets):
    jars = OrderedDict()
    excludes = set()

    # Support the ivy force concept when we sanely can for internal dep conflicts.
    # TODO(John Sirois): Consider supporting / implementing the configured ivy revision picking
    # strategy generally.
    def add_jar(jar):
      coordinate = (jar.org, jar.name)
      existing = jars.get(coordinate)
      jars[coordinate] = jar if not existing else (
        self._resolve_conflict(existing=existing, proposed=jar)
      )

    def collect_jars(target):
      if target.is_jvm or target.is_jar_library:
        for jar in target.jar_dependencies:
          if jar.rev:
            add_jar(jar)

      target_excludes = target.payload.get_field_value('excludes')
      if target_excludes:
        excludes.update(target_excludes)

    for target in targets:
      target.walk(collect_jars)

    return jars.values(), excludes

  def _resolve_conflict(self, existing, proposed):
    if proposed == existing:
      if proposed.force:
        return proposed
      return existing
    elif existing.force and proposed.force:
      raise TaskError('Cannot force %s#%s to both rev %s and %s' % (
        proposed.org, proposed.name, existing.rev, proposed.rev
      ))
    elif existing.force:
      self._log.debug('Ignoring rev %s for %s#%s already forced to %s' % (
        proposed.rev, proposed.org, proposed.name, existing.rev
      ))
      return existing
    elif proposed.force:
      self._log.debug('Forcing %s#%s from %s to %s' % (
        proposed.org, proposed.name, existing.rev, proposed.rev
      ))
      return proposed
    else:
      try:
        if Revision.lenient(proposed.rev) > Revision.lenient(existing.rev):
          self._log.debug('Upgrading %s#%s from rev %s  to %s' % (
            proposed.org, proposed.name, existing.rev, proposed.rev,
          ))
          return proposed
        else:
          return existing
      except Revision.BadRevision as e:
        raise TaskError('Failed to parse jar revision', e)

  def _is_mutable(self, jar):
    if jar.mutable is not None:
      return jar.mutable
    return False

  def _generate_jar_template(self, jar, confs):
    template = TemplateData(
        org=jar.org,
        module=jar.name,
        version=jar.rev,
        mutable=self._is_mutable(jar),
        force=jar.force,
        excludes=[self._generate_exclude_template(exclude) for exclude in jar.excludes],
        transitive=jar.transitive,
        artifacts=jar.artifacts,
        configurations=[conf for conf in jar.configurations if conf in confs])
    return template

  def mapto_dir(self):
    """Subclasses can override to establish an isolated jar mapping directory."""
    return os.path.join(self._workdir, 'mapped-jars')

  def mapjars(self, genmap, target, executor, workunit_factory=None, jars=None):
    """Resolves jars for the target and stores their locations in genmap.
    :param genmap: The jar_dependencies ProductMapping entry for the required products.
    :param target: The target whose jar dependencies are being retrieved.
    :param jars: If specified, resolves the given jars rather than
    :type jars: List of :class:`pants.backend.jvm.targets.jar_dependency.JarDependency` (jar())
      objects.
    """
    mapdir = os.path.join(self.mapto_dir(), target.id)
    safe_mkdir(mapdir, clean=True)
    ivyargs = [
      '-retrieve', '%s/[organisation]/[artifact]/[conf]/'
                   '[organisation]-[artifact]-[revision](-[classifier]).[ext]' % mapdir,
      '-symlink',
    ]
    self.exec_ivy(mapdir,
                  [target],
                  ivyargs,
                  confs=target.payload.configurations,
                  ivy=Bootstrapper.default_ivy(executor),
                  workunit_factory=workunit_factory,
                  workunit_name='map-jars',
                  jars=jars)

    for org in os.listdir(mapdir):
      orgdir = os.path.join(mapdir, org)
      if os.path.isdir(orgdir):
        for name in os.listdir(orgdir):
          artifactdir = os.path.join(orgdir, name)
          if os.path.isdir(artifactdir):
            for conf in os.listdir(artifactdir):
              confdir = os.path.join(artifactdir, conf)
              for f in os.listdir(confdir):
                if self.is_mappable_artifact(org, name, f):
                  # TODO(John Sirois): kill the org and (org, name) exclude mappings in favor of a
                  # conf whitelist
                  genmap.add(org, confdir).append(f)
                  genmap.add((org, name), confdir).append(f)

                  genmap.add(target, confdir).append(f)
                  genmap.add((target, conf), confdir).append(f)
                  genmap.add((org, name, conf), confdir).append(f)

  ivy_lock = threading.RLock()

  def exec_ivy(self,
               target_workdir,
               targets,
               args,
               confs=None,
               ivy=None,
               workunit_name='ivy',
               workunit_factory=None,
               symlink_ivyxml=False,
               jars=None):

    ivy = ivy or Bootstrapper.default_ivy()
    if not isinstance(ivy, Ivy):
      raise ValueError('The ivy argument supplied must be an Ivy instance, given %s of type %s'
                       % (ivy, type(ivy)))

    ivyxml = os.path.join(target_workdir, 'ivy.xml')

    if not jars:
      jars, excludes = self._calculate_classpath(targets)
    else:
      excludes = set()

    ivy_args = ['-ivy', ivyxml]

    confs_to_resolve = confs or ['default']
    ivy_args.append('-confs')
    ivy_args.extend(confs_to_resolve)

    ivy_args.extend(args)
    if not self._transitive:
      ivy_args.append('-notransitive')
    ivy_args.extend(self._args)

    def safe_link(src, dest):
      try:
        os.unlink(dest)
      except OSError as e:
        if e.errno != errno.ENOENT:
          raise
      os.symlink(src, dest)

    with IvyUtils.ivy_lock:
      self._generate_ivy(targets, jars, excludes, ivyxml, confs_to_resolve)
      runner = ivy.runner(jvm_options=self._jvm_options, args=ivy_args)
      try:
        result = util.execute_runner(runner,
                                     workunit_factory=workunit_factory,
                                     workunit_name=workunit_name)

        # Symlink to the current ivy.xml file (useful for IDEs that read it).
        if symlink_ivyxml:
          ivyxml_symlink = os.path.join(self._workdir, 'ivy.xml')
          safe_link(ivyxml, ivyxml_symlink)

        if result != 0:
          raise TaskError('Ivy returned %d' % result)
      except runner.executor.Error as e:
        raise TaskError(e)
