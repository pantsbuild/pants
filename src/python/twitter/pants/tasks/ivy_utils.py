# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================
from __future__ import print_function

from collections import namedtuple, defaultdict
from contextlib import contextmanager
import hashlib
import os
import xml
import pkgutil
import re
import threading

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants import binary_util, get_buildroot, is_internal, is_jar, is_jvm, is_concrete
from twitter.pants.base.generator import Generator, TemplateData
from twitter.pants.base.revision import Revision
from twitter.pants.base.target import Target
from twitter.pants.tasks import TaskError


IvyModuleRef = namedtuple('IvyModuleRef', ['org', 'name', 'rev', 'conf'])
IvyArtifact = namedtuple('IvyArtifact', ['path'])
IvyModule = namedtuple('IvyModule', ['ref', 'artifacts', 'callers'])

 
class IvyInfo(object):
  def __init__(self):
    self.modules_by_ref = {}  # Map from ref to referenced module.
    self.deps_by_caller = defaultdict(OrderedSet)  # Map from ref of caller to refs of modules required by that caller.

  def add_module(self, module):
    self.modules_by_ref[module.ref] = module
    for caller in module.callers:
      self.deps_by_caller[caller].add(module.ref)


class IvyUtils(object):
  """Useful methods related to interaction with ivy."""
  def __init__(self, config, options, log):
    self._log = log
    self._config = config
    self._options = options

    # TODO(pl): This is super awful, but options doesn't have a nice way to get out
    # attributes that might not be there, and even then the attribute value might be
    # None, which we still want to override
    # Benjy thinks we should probably hoist these options to the global set of options,
    # rather than just keeping them within IvyResolve.setup_parser
    self._cachedir = (getattr(options, 'ivy_resolve_cache', None) or
                      config.get('ivy', 'cache_dir'))

    self._ivy_args = getattr(options, 'ivy_args', [])
    self._mutable_pattern = (getattr(options, 'ivy_mutable_pattern', None) or
                             config.get('ivy-resolve', 'mutable_pattern', default=None))

    self._ivy_settings = config.get('ivy', 'ivy_settings')
    self._transitive = config.getbool('ivy-resolve', 'transitive')
    self._opts = config.getlist('ivy-resolve', 'args')
    self._work_dir = config.get('ivy-resolve', 'workdir')
    self._template_path = os.path.join('templates', 'ivy_resolve', 'ivy.mustache')
    self._confs = config.getlist('ivy-resolve', 'confs')
    self._classpath_file = os.path.join(self._work_dir, 'classpath')
    self._classpath_dir = os.path.join(self._work_dir, 'mapped')


    if self._mutable_pattern:
      try:
        self._mutable_pattern = re.compile(self._mutable_pattern)
      except re.error as e:
        raise TaskError('Invalid mutable pattern specified: %s %s' % (self._mutable_pattern, e))

    def parse_override(override):
      match = re.match(r'^([^#]+)#([^=]+)=([^\s]+)$', override)
      if not match:
        raise TaskError('Invalid dependency override: %s' % override)

      org, name, rev_or_url = match.groups()

      def fmt_message(message, template):
        return message % dict(
          overridden='%s#%s;%s' % (template.org, template.module, template.version),
          rev=rev_or_url,
          url=rev_or_url
        )

      def replace_rev(template):
        _log.info(fmt_message('Overrode %(overridden)s with rev %(rev)s', template))
        return template.extend(version=rev_or_url, url=None, force=True)

      def replace_url(template):
        _log.info(fmt_message('Overrode %(overridden)s with snapshot at %(url)s', template))
        return template.extend(version='SNAPSHOT', url=rev_or_url, force=True)

      replace = replace_url if re.match(r'^\w+://.+', rev_or_url) else replace_rev
      return (org, name), replace
    self._overrides = {}
    # TODO(pl): See above comment wrt options
    if hasattr(options, 'ivy_resolve_overrides') and options.ivy_resolve_overrides:
      self._overrides.update(parse_override(o) for o in options.ivy_resolve_overrides)

  @staticmethod
  @contextmanager
  def cachepath(path):
    if not os.path.exists(path):
      yield ()
    else:
      with safe_open(path, 'r') as cp:
        yield (path.strip() for path in cp.read().split(os.pathsep) if path.strip())

  def identify(self, targets):
    targets = list(targets)
    if len(targets) == 1 and hasattr(targets[0], 'provides') and targets[0].provides:
      return targets[0].provides.org, targets[0].provides.name
    else:
      return 'internal', Target.maybe_readable_identify(targets)

  def xml_report_path(self, targets, conf):
    """The path to the xml report ivy creates after a retrieve."""
    org, name = self.identify(targets)
    return os.path.join(self._cachedir, '%s-%s-%s.xml' % (org, name, conf))

  def parse_xml_report(self, targets, conf):
    """Returns the IvyInfo representing the info in the xml report, or None of no report exists."""
    path = self.xml_report_path(targets, conf)
    if not os.path.exists(path):
      return None

    ret = IvyInfo()
    etree = xml.etree.cElementTree.parse(self.xml_report_path(targets, conf))
    doc = etree.getroot()
    for module in doc.findall('dependencies/module'):
      org = module.get('organisation')
      name = module.get('name')
      for revision in module.findall('revision'):
        rev = revision.get('name')
        confs = self._split_conf(revision.get('conf'))
        artifacts = []
        for artifact in revision.findall('artifacts/artifact'):
          artifacts.append(IvyArtifact(artifact.get('location')))
        callers = []
        for caller in revision.findall('caller'):
          for caller_conf in self._split_conf(caller.get('conf')):
            callers.append(IvyModuleRef(caller.get('organisation'), caller.get('name'),
              caller.get('callerrev'), caller_conf))
        for conf in confs:
          ret.add_module(IvyModule(IvyModuleRef(org, name, rev, conf), artifacts, callers))
    return ret

  def _split_conf(self, conf):
    return [c.strip() for c in conf.split(',')]

  def _extract_classpathdeps(self, targets):
    """Subclasses can override to filter out a set of targets that should be resolved for classpath
    dependencies.
    """
    def is_classpath(target):
      return is_jar(target) or (
        is_internal(target) and any(jar for jar in target.jar_dependencies if jar.rev)
      )

    classpath_deps = OrderedSet()
    for target in targets:
      classpath_deps.update(filter(is_classpath, filter(is_concrete, target.resolve())))
    return classpath_deps

  def _generate_ivy(self, targets, jars, excludes, ivyxml):
    org, name = self.identify(targets)
    template_data = TemplateData(
      org=org,
      module=name,
      version='latest.integration',
      publications=None,
      is_idl=False,
      dependencies=[self._generate_jar_template(jar) for jar in jars],
      excludes=[self._generate_exclude_template(exclude) for exclude in excludes]
    )

    safe_mkdir(os.path.dirname(ivyxml))
    with open(ivyxml, 'w') as output:
      generator = Generator(pkgutil.get_data(__name__, self._template_path),
                            root_dir=get_buildroot(),
                            lib=template_data)
      generator.write(output)

  def _calculate_classpath(self, targets):
    def is_jardependant(target):
      return is_jar(target) or is_jvm(target)

    jars = {}
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
      if is_jar(target):
        add_jar(target)
      elif target.jar_dependencies:
        for jar in target.jar_dependencies:
          if jar.rev:
            add_jar(jar)

      # Lift jvm target-level excludes up to the global excludes set
      if is_jvm(target) and target.excludes:
        excludes.update(target.excludes)

    for target in targets:
      target.walk(collect_jars, is_jardependant)

    return jars.values(), excludes

  def _resolve_conflict(self, existing, proposed):
    if proposed == existing:
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
    if self._mutable_pattern:
      return self._mutable_pattern.match(jar.rev)
    return False

  def _generate_jar_template(self, jar):
    template = TemplateData(
      org=jar.org,
      module=jar.name,
      version=jar.rev,
      mutable=self._is_mutable(jar),
      force=jar.force,
      excludes=[self._generate_exclude_template(exclude) for exclude in jar.excludes],
      transitive=jar.transitive,
      artifacts=jar.artifacts,
      is_idl='idl' in jar._configurations,
      configurations=';'.join(jar._configurations),
    )
    override = self._overrides.get((jar.org, jar.name))
    return override(template) if override else template

  def _generate_exclude_template(self, exclude):
    return TemplateData(org=exclude.org, name=exclude.name)

  @staticmethod
  def is_mappable_artifact(path):
    """Subclasses can override to determine whether a given path represents a mappable artifact."""
    return path.endswith('.jar') or path.endswith('.war')

  def mapjars(self, genmap, target, java_runner):
    """
    Parameters:
      genmap: the jar_dependencies ProductMapping entry for the required products.
      target: the target whose jar dependencies are being retrieved.
    """
    mapdir = os.path.join(self._mapto_dir(), target.id)
    safe_mkdir(mapdir, clean=True)
    ivyargs = [
      '-retrieve', '%s/[organisation]/[artifact]/[conf]/'
                   '[organisation]-[artifact]-[revision](-[classifier]).[ext]' % mapdir,
      '-symlink',
      '-confs',
    ]
    ivyargs.extend(target.configurations or self._confs)
    self.exec_ivy(mapdir, [target], ivyargs, runjava=java_runner)

    for org in os.listdir(mapdir):
      orgdir = os.path.join(mapdir, org)
      if os.path.isdir(orgdir):
        for name in os.listdir(orgdir):
          artifactdir = os.path.join(orgdir, name)
          if os.path.isdir(artifactdir):
            for conf in os.listdir(artifactdir):
              confdir = os.path.join(artifactdir, conf)
              for file in os.listdir(confdir):
                if self.is_mappable_artifact(file):
                  # TODO(John Sirois): kill the org and (org, name) exclude mappings in favor of a
                  # conf whitelist
                  genmap.add(org, confdir).append(file)
                  genmap.add((org, name), confdir).append(file)

                  genmap.add(target, confdir).append(file)
                  genmap.add((target, conf), confdir).append(file)
                  genmap.add((org, name, conf), confdir).append(file)

  def _mapfor_typename(self):
    """Subclasses can override to identify the product map typename that should trigger jar mapping.
    """
    return 'jar_dependencies'

  def _mapto_dir(self):
    """Subclasses can override to establish an isolated jar mapping directory."""
    return os.path.join(self._work_dir, 'mapped-jars')

  ivy_lock = threading.RLock()
  def exec_ivy(self, target_workdir, targets, args, runjava=None,
               workunit_name='ivy', workunit_factory=None, ivy_classpath=None):
    ivy_classpath = ivy_classpath if ivy_classpath else self._config.getlist('ivy', 'classpath')
    runjava = runjava or binary_util.runjava_indivisible
    ivyxml = os.path.join(target_workdir, 'ivy.xml')
    jars, excludes = self._calculate_classpath(targets)

    ivy_opts = [
      '-settings', self._ivy_settings,
      '-cache', self._cachedir,
      '-ivy', ivyxml,
    ]
    ivy_opts.extend(args)
    if not self._transitive:
      ivy_opts.append('-notransitive')
    ivy_opts.extend(self._opts)
    ivy_opts.extend(self._ivy_args)

    runjava_args = dict(
      main='org.apache.ivy.Main',
      opts=ivy_opts,
      workunit_name=workunit_name,
      classpath=ivy_classpath,
      workunit_factory=workunit_factory,
    )

    with IvyUtils.ivy_lock:
      self._generate_ivy(targets, jars, excludes, ivyxml)
      result = runjava(**runjava_args)

    if result != 0:
      raise TaskError('org.apache.ivy.Main returned %d' % result)

