# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

import hashlib
import os
import pkgutil
import re
import shutil
import time

from contextlib import contextmanager

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants import binary_util, get_buildroot, is_internal, is_jar, is_jvm, is_concrete
from twitter.pants.base.generator import Generator, TemplateData
from twitter.pants.base.revision import Revision
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.cache_manager import VersionedTargetSet
from twitter.pants.tasks.ivy_utils import IvyUtils
from twitter.pants.tasks.nailgun_task import NailgunTask


class IvyResolve(NailgunTask):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    flag = mkflag('override')
    option_group.add_option(flag, action='append', dest='ivy_resolve_overrides',
                            help='''Specifies a jar dependency override in the form:
                            [org]#[name]=(revision|url)

                            For example, to specify 2 overrides:
                            %(flag)s=com.foo#bar=0.1.2 \\
                            %(flag)s=com.baz#spam=file:///tmp/spam.jar
                            ''' % dict(flag=flag))

    report = mkflag("report")
    option_group.add_option(report, mkflag("report", negate=True), dest = "ivy_resolve_report",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help = "[%default] Generate an ivy resolve html report")

    option_group.add_option(mkflag("open"), mkflag("open", negate=True),
                            dest="ivy_resolve_open", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%%default] Attempt to open the generated ivy resolve report "
                                 "in a browser (implies %s)." % report)

    option_group.add_option(mkflag("outdir"), dest="ivy_resolve_outdir",
                            help="Emit ivy report outputs in to this directory.")

    option_group.add_option(mkflag("cache"), dest="ivy_resolve_cache",
                            help="Use this directory as the ivy cache, instead of the "
                                 "default specified in pants.ini.")

    option_group.add_option(mkflag("args"), dest="ivy_args", action="append", default=[],
                            help = "Pass these extra args to ivy.")

    option_group.add_option(mkflag("mutable-pattern"), dest="ivy_mutable_pattern",
                            help="If specified, all artifact revisions matching this pattern will "
                                 "be treated as mutable unless a matching artifact explicitly "
                                 "marks mutable as False.")

  def __init__(self, context, confs=None):
    classpath = context.config.getlist('ivy', 'classpath')
    nailgun_dir = context.config.get('ivy-resolve', 'nailgun_dir')
    NailgunTask.__init__(self, context, classpath=classpath, workdir=nailgun_dir)

    self._ivy_settings = context.config.get('ivy', 'ivy_settings')
    self._cachedir = context.options.ivy_resolve_cache or context.config.get('ivy', 'cache_dir')
    self._confs = confs or context.config.getlist('ivy-resolve', 'confs')
    self._transitive = context.config.getbool('ivy-resolve', 'transitive')
    self._opts = context.config.getlist('ivy-resolve', 'args')
    self._ivy_args = context.options.ivy_args

    self._mutable_pattern = (context.options.ivy_mutable_pattern or
                             context.config.get('ivy-resolve', 'mutable_pattern', default=None))
    if self._mutable_pattern:
      try:
        self._mutable_pattern = re.compile(self._mutable_pattern)
      except re.error as e:
        raise TaskError('Invalid mutable pattern specified: %s %s' % (self._mutable_pattern, e))

    self._profile = context.config.get('ivy-resolve', 'profile')

    self._template_path = os.path.join('templates', 'ivy_resolve', 'ivy.mustache')

    self._work_dir = context.config.get('ivy-resolve', 'workdir')
    self._classpath_dir = os.path.join(self._work_dir, 'mapped')

    self._outdir = context.options.ivy_resolve_outdir or os.path.join(self._work_dir, 'reports')
    self._open = context.options.ivy_resolve_open
    self._report = self._open or context.options.ivy_resolve_report
    self._ivy_utils = IvyUtils(context, self._cachedir)
    context.products.require_data('exclusives_groups')

    # Typically this should be a local cache only, since classpaths aren't portable.
    artifact_cache_spec = context.config.getlist('ivy-resolve', 'artifact_caches', default=[])
    self.setup_artifact_cache(artifact_cache_spec)

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
        context.log.info(fmt_message('Overrode %(overridden)s with rev %(rev)s', template))
        return template.extend(version=rev_or_url, url=None, force=True)

      def replace_url(template):
        context.log.info(fmt_message('Overrode %(overridden)s with snapshot at %(url)s', template))
        return template.extend(version='SNAPSHOT', url=rev_or_url, force=True)

      replace = replace_url if re.match(r'^\w+://.+', rev_or_url) else replace_rev
      return (org, name), replace

    self._overrides = {}
    if context.options.ivy_resolve_overrides:
      self._overrides.update(parse_override(o) for o in context.options.ivy_resolve_overrides)

  def invalidate_for(self):
    return self.context.options.ivy_resolve_overrides

  def execute(self, targets):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """
    def dirname_for_requested_targets(targets):
      """Where we put the classpath file for this set of targets."""
      sha = hashlib.sha1()
      for t in targets:
        sha.update(t.id)
      return sha.hexdigest()

    def is_classpath(target):
      return is_jar(target) or (
        is_internal(target) and any(jar for jar in target.jar_dependencies if jar.rev)
      )

    groups = self.context.products.get_data('exclusives_groups')

    # Below, need to take the code that actually execs ivy, and invoke it once for each
    # group. Then after running ivy, we need to take the resulting classpath, and load it into
    # the build products.

    # The set of groups we need to consider is complicated:
    # - If there are no conflicting exclusives (ie, there's only one entry in the map),
    #   then we just do the one.
    # - If there are conflicts, then there will be at least three entries in the groups map:
    #   - the group with no exclusives (X)
    #   - the two groups that are in conflict (A and B).
    # In the latter case, we need to do the resolve twice: Once for A+X, and once for B+X,
    # because things in A and B can depend on things in X; and so they can indirectly depend
    # on the dependencies of X. (I think this well be covered by the computed transitive dependencies of
    # A and B. But before pushing this change, review this comment, and make sure that this is
    # working correctly.
    for group_key in groups.get_group_keys():
      # Narrow the groups target set to just the set of targets that we're supposed to build.
      # Normally, this shouldn't be different from the contents of the group.
      group_targets = groups.get_targets_for_group_key(group_key) & set(targets)

      classpath_targets = OrderedSet()
      for target in group_targets:
        classpath_targets.update(filter(is_classpath, filter(is_concrete, target.resolve())))

      if len(classpath_targets) == 0:
        continue  # Nothing to do.

      target_workdir = os.path.join(self._work_dir, dirname_for_requested_targets(group_targets))
      target_classpath_file = os.path.join(target_workdir, 'classpath')
      with self.invalidated(classpath_targets, only_buildfiles=True,
                            invalidate_dependents=True) as invalidation_check:
        # Note that it's possible for all targets to be valid but for no classpath file to exist at
        # target_classpath_file, e.g., if we previously built a superset of targets.
        if invalidation_check.invalid_vts or not os.path.exists(target_classpath_file):
          # TODO(benjy): s/targets/classpath_targets/ ??
          self._exec_ivy(target_workdir, targets, [
            '-cachepath', target_classpath_file,
            '-confs'
          ] + self._confs)

          if not os.path.exists(target_classpath_file):
            raise TaskError('Ivy failed to create classpath file at %s %s' % target_classpath_file)
          if self.get_artifact_cache() and self.context.options.write_to_artifact_cache:
            global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
            self.update_artifact_cache([(global_vts, [target_classpath_file])])

      with self._cachepath(target_classpath_file) as classpath:
        for path in classpath:
          if self._map_jar(path):
            for conf in self._confs:
              groups.update_compatible_classpaths(group_key, [(conf, path.strip())])

    if self._report:
      self._generate_ivy_report()

    if self.context.products.isrequired("ivy_jar_products"):
      self._populate_ivy_jar_products()

    create_jardeps_for = self.context.products.isrequired(self._mapfor_typename())
    if create_jardeps_for:
      genmap = self.context.products.get(self._mapfor_typename())
      for target in filter(create_jardeps_for, targets):
        self._mapjars(genmap, target)

  def check_artifact_cache_for(self, invalidation_check):
    # Ivy resolution is an output dependent on the entire target set, and is not divisible
    # by target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]

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

  def _generate_ivy(self, jars, excludes, ivyxml):
    org, name = self._ivy_utils.identify()
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
                            root_dir = get_buildroot(),
                            lib = template_data)
      generator.write(output)

  def _populate_ivy_jar_products(self):
    """
    Populate the build products with an IvyInfo object for each
    generated ivy report.
    For each configuration used to run ivy, a build product entry
    is generated for the tuple ("ivy", configuration, ivyinfo)
    """
    genmap = self.context.products.get('ivy_jar_products')
    # For each of the ivy reports:
    for conf in self._confs:
      # parse the report file, and put it into the build products.
      # This is sort-of an abuse of the build-products. But build products
      # are already so abused, and this really does make sense.
      ivyinfo = self._ivy_utils.parse_xml_report(conf)
      if ivyinfo:
        genmap.add("ivy", conf, [ivyinfo])

  def _generate_ivy_report(self):
    def make_empty_report(report, organisation, module, conf):
      no_deps_xml = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="ivy-report.xsl"?>
<ivy-report version="1.0">
	<info
		organisation="%(organisation)s"
		module="%(module)s"
		revision="latest.integration"
		conf="%(conf)s"
		confs="%(conf)s"
		date="%(timestamp)s"/>
</ivy-report>""" % dict(organisation=organisation,
                        module=module,
                        conf=conf,
                        timestamp=time.strftime('%Y%m%d%H%M%S'))
      with open(report, 'w') as report_handle:
        print(no_deps_xml, file=report_handle)

    classpath = self.profile_classpath(self._profile)

    reports = []
    org, name = self._ivy_utils.identify()
    xsl = os.path.join(self._cachedir, 'ivy-report.xsl')
    safe_mkdir(self._outdir, clean=True)
    for conf in self._confs:
      params = dict(
        org=org,
        name=name,
        conf=conf
      )
      xml = os.path.join(self._cachedir, '%(org)s-%(name)s-%(conf)s.xml' % params)
      if not os.path.exists(xml):
        make_empty_report(xml, org, name, conf)
      #xml = self._ivy_utils.xml_report_path(conf)
      out = os.path.join(self._outdir, '%(org)s-%(name)s-%(conf)s.html' % params)
      opts = ['-IN', xml, '-XSL', xsl, '-OUT', out]
      if 0 != self.runjava_indivisible('org.apache.xalan.xslt.Process', classpath=classpath,
                                       opts=opts, workunit_name='report'):
        raise TaskError
      reports.append(out)

    css = os.path.join(self._outdir, 'ivy-report.css')
    if os.path.exists(css):
      os.unlink(css)
    shutil.copy(os.path.join(self._cachedir, 'ivy-report.css'), self._outdir)

    if self._open:
      binary_util.ui_open(*reports)

  def _calculate_classpath(self, targets):
    def is_jardependent(target):
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
      target.walk(collect_jars, is_jardependent)

    return jars.values(), excludes

  def _resolve_conflict(self, existing, proposed):
    if proposed == existing:
      return existing
    elif existing.force and proposed.force:
      raise TaskError('Cannot force %s#%s to both rev %s and %s' % (
        proposed.org, proposed.name, existing.rev, proposed.rev
      ))
    elif existing.force:
      self.context.log.debug('Ignoring rev %s for %s#%s already forced to %s' % (
        proposed.rev, proposed.org, proposed.name, existing.rev
      ))
      return existing
    elif proposed.force:
      self.context.log.debug('Forcing %s#%s from %s to %s' % (
        proposed.org, proposed.name, existing.rev, proposed.rev
      ))
      return proposed
    else:
      try:
        if Revision.lenient(proposed.rev) > Revision.lenient(existing.rev):
          self.context.log.debug('Upgrading %s#%s from rev %s  to %s' % (
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
    template=TemplateData(
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

  @contextmanager
  def _cachepath(self, path):
    if not os.path.exists(path):
      yield ()
    else:
      with safe_open(path, 'r') as cp:
        yield (path.strip() for path in cp.read().split(os.pathsep) if path.strip())

  def _mapjars(self, genmap, target):
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
    self._exec_ivy(mapdir, [target], ivyargs)

    for org in os.listdir(mapdir):
      orgdir = os.path.join(mapdir, org)
      if os.path.isdir(orgdir):
        for name in os.listdir(orgdir):
          artifactdir = os.path.join(orgdir, name)
          if os.path.isdir(artifactdir):
            for conf in os.listdir(artifactdir):
              confdir = os.path.join(artifactdir, conf)
              for file in os.listdir(confdir):
                if self._map_jar(file):
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

  def _map_jar(self, path):
    """Subclasses can override to determine whether a given path represents a mappable artifact."""
    return path.endswith('.jar') or path.endswith('.war')

  def _exec_ivy(self, target_workdir, targets, args):
    ivyxml = os.path.join(target_workdir, 'ivy.xml')
    jars, excludes = self._calculate_classpath(targets)
    self._generate_ivy(jars, excludes, ivyxml)

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

    result = self.runjava_indivisible('org.apache.ivy.Main', opts=ivy_opts, workunit_name='ivy')
    if result != 0:
      raise TaskError('org.apache.ivy.Main returned %d' % result)
