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

from collections import defaultdict
from contextlib import contextmanager

import logging
import os
import re
import shutil
import time

from twitter.common.collections import OrderedDict
from twitter.common.dirutil import safe_mkdir, safe_open
from twitter.common.log import LogOptions

from twitter.pants import binary_util
from twitter.pants.base.generator import TemplateData
from twitter.pants.base.revision import Revision
from twitter.pants.ivy import Bootstrapper, Ivy

from .cache_manager import VersionedTargetSet
from .ivy_utils import IvyUtils
from .nailgun_task import NailgunTask

from . import TaskError


class IvyResolve(NailgunTask):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    flag = mkflag('override')
    option_group.add_option(flag, action='append', dest='ivy_resolve_overrides',
                            help="""Specifies a jar dependency override in the form:
                            [org]#[name]=(revision|url)

                            For example, to specify 2 overrides:
                            %(flag)s=com.foo#bar=0.1.2 \\
                            %(flag)s=com.baz#spam=file:///tmp/spam.jar
                            """ % dict(flag=flag))

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

    option_group.add_option(mkflag("args"), dest="ivy_args", action="append", default=[],
                            help = "Pass these extra args to ivy.")

    option_group.add_option(mkflag("mutable-pattern"), dest="ivy_mutable_pattern",
                            help="If specified, all artifact revisions matching this pattern will "
                                 "be treated as mutable unless a matching artifact explicitly "
                                 "marks mutable as False.")

  def __init__(self, context, confs=None):
    super(IvyResolve, self).__init__(context)

    self._ivy_bootstrapper = Bootstrapper.instance()
    self._cachedir = self._ivy_bootstrapper.ivy_cache_dir

    self._confs = confs or context.config.getlist('ivy-resolve', 'confs', default=['default'])
    self._transitive = context.config.getbool('ivy-resolve', 'transitive', default=True)

    self._jvm_args = context.config.getlist('ivy-resolve', 'jvm_args', default=[])
    # Disable cache in File.getCanonicalPath() to make Ivy work with -symlink option properly on
    # nailgun.
    self._jvm_args.append('-Dsun.io.useCanonCaches=false')

    self._ivy_args = (context.options.ivy_args or
                      context.config.getlist('ivy-resolve', 'ivy_args', default=[]))

    self._mutable_pattern = (context.options.ivy_mutable_pattern or
                             context.config.get('ivy-resolve', 'mutable_pattern', default=None))
    if self._mutable_pattern:
      try:
        self._mutable_pattern = re.compile(self._mutable_pattern)
      except re.error as e:
        raise TaskError('Invalid mutable pattern specified: %s %s' % (self._mutable_pattern, e))

    self._work_dir = context.config.get('ivy-resolve', 'workdir')
    self._classpath_dir = os.path.join(self._work_dir, 'mapped')

    self._outdir = context.options.ivy_resolve_outdir or os.path.join(self._work_dir, 'reports')
    self._open = context.options.ivy_resolve_open
    self._report = self._open or context.options.ivy_resolve_report

    self._ivy_bootstrap_key = 'ivy'
    ivy_bootstrap_tools = context.config.getlist('ivy-resolve', 'bootstrap-tools', ':xalan')
    self._jvm_tool_bootstrapper.register_jvm_tool(self._ivy_bootstrap_key, ivy_bootstrap_tools)

    self._ivy_utils = IvyUtils(config=context.config,
                               options=context.options,
                               log=context.log)
    context.products.require_data('exclusives_groups')

    # Typically this should be a local cache only, since classpaths aren't portable.
    self.setup_artifact_cache_from_config(config_section='ivy-resolve')

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

  def invalidate_for(self):
    return self.context.options.ivy_resolve_overrides

  def execute(self, targets):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """
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
    # on the dependencies of X.
    # (I think this well be covered by the computed transitive dependencies of
    # A and B. But before pushing this change, review this comment, and make sure that this is
    # working correctly.)
    for group_key in groups.get_group_keys():
      # Narrow the groups target set to just the set of targets that we're supposed to build.
      # Normally, this shouldn't be different from the contents of the group.
      group_targets = groups.get_targets_for_group_key(group_key) & set(targets)

      # NOTE(pl): The symlinked ivy.xml (for IDEs, particularly IntelliJ) in the presence of
      # multiple exclusives groups will end up as the last exclusives group run.  I'd like to
      # deprecate this eventually, but some people rely on it, and it's not clear to me right now
      # whether telling them to use IdeaGen instead is feasible.
      classpath = self.ivy_resolve(group_targets,
                                   java_runner=self.runjava_indivisible,
                                   symlink_ivyxml=True)
      if self.context.products.isrequired('ivy_jar_products'):
        self._populate_ivy_jar_products(group_targets)
      for conf in self._confs:
        for path in classpath:
          groups.update_compatible_classpaths(group_key, [(conf, path)])

      if self._report:
        self._generate_ivy_report(group_targets)

    create_jardeps_for = self.context.products.isrequired(self._ivy_utils._mapfor_typename())
    if create_jardeps_for:
      genmap = self.context.products.get(self._ivy_utils._mapfor_typename())
      for target in filter(create_jardeps_for, targets):
        self._ivy_utils.mapjars(genmap, target, java_runner=self.runjava_indivisible)

  def check_artifact_cache_for(self, invalidation_check):
    # Ivy resolution is an output dependent on the entire target set, and is not divisible
    # by target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]

  def _populate_ivy_jar_products(self, targets):
    """Populate the build products with an IvyInfo object for each generated ivy report."""
    ivy_products = self.context.products.get_data('ivy_jar_products') or defaultdict(list)
    for conf in self._confs:
      ivyinfo = self._ivy_utils.parse_xml_report(targets, conf)
      if ivyinfo:
        ivy_products[conf].append(ivyinfo)  # Value is a list, to accommodate multiple exclusives groups.
    self.context.products.set_data('ivy_jar_products', ivy_products)

  def _generate_ivy_report(self, targets):
    def make_empty_report(report, organisation, module, conf):
      no_deps_xml_template = """
        <?xml version="1.0" encoding="UTF-8"?>
        <?xml-stylesheet type="text/xsl" href="ivy-report.xsl"?>
        <ivy-report version="1.0">
          <info
            organisation="%(organisation)s"
            module="%(module)s"
            revision="latest.integration"
            conf="%(conf)s"
            confs="%(conf)s"
            date="%(timestamp)s"/>
        </ivy-report>
      """
      no_deps_xml = no_deps_xml_template % dict(organisation=organisation,
                                                module=module,
                                                conf=conf,
                                                timestamp=time.strftime('%Y%m%d%H%M%S'))
      with open(report, 'w') as report_handle:
        print(no_deps_xml, file=report_handle)

    classpath = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._ivy_bootstrap_key,
                                                                   self.runjava_indivisible)

    reports = []
    org, name = self._ivy_utils.identify(targets)
    xsl = os.path.join(self._cachedir, 'ivy-report.xsl')

    # Xalan needs this dir to exist - ensure that, but do no more - we have no clue where this
    # points.
    safe_mkdir(self._outdir, clean=False)

    for conf in self._confs:
      params = dict(org=org, name=name, conf=conf)
      xml = self._ivy_utils.xml_report_path(targets, conf)
      if not os.path.exists(xml):
        make_empty_report(xml, org, name, conf)
      out = os.path.join(self._outdir, '%(org)s-%(name)s-%(conf)s.html' % params)
      args = ['-IN', xml, '-XSL', xsl, '-OUT', out]
      if 0 != self.runjava_indivisible('org.apache.xalan.xslt.Process', classpath=classpath,
                                       args=args, workunit_name='report'):
        raise TaskError
      reports.append(out)

    css = os.path.join(self._outdir, 'ivy-report.css')
    if os.path.exists(css):
      os.unlink(css)
    shutil.copy(os.path.join(self._cachedir, 'ivy-report.css'), self._outdir)

    if self._open:
      binary_util.ui_open(*reports)

  ##################################################################################################
  # TODO(John Sirois): XXX from here down may be unused code or need to move elsewhere!
  ##################################################################################################
  def _identify(self):
    if len(self.context.target_roots) == 1:
      target = self.context.target_roots[0]
      if hasattr(target, 'provides') and target.provides:
        return target.provides.org, target.provides.name
      else:
        return 'internal', target.id
    else:
      return 'internal', self.context.id

  def _calculate_classpath(self, targets):
    def is_jardependant(target):
      return target.is_jar or target.is_jvm

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
      if target.is_jar:
        add_jar(target)
      elif target.jar_dependencies:
        for jar in target.jar_dependencies:
          if jar.rev:
            add_jar(jar)

      # Lift jvm target-level excludes up to the global excludes set
      if target.is_jvm and target.excludes:
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

  def _generate_override_template(self, jar):
    return TemplateData(org=jar.org, module=jar.module, version=jar.version)

  @contextmanager
  def _cachepath(self, file):
    if not os.path.exists(file):
      yield ()
    else:
      with safe_open(file, 'r') as cp:
        yield (path.strip() for path in cp.read().split(os.pathsep) if path.strip())

  def _mapjars(self, genmap, target):
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
                if self._map_jar(org, name, conf, file):
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

  def _map_jar(self, org, name, conf, path):
    """Subclasses can override to determine whether a given path represents a mappable artifact."""
    return path.endswith('.jar')

  def _exec_ivy(self, target_workdir, targets, args):
    ivyxml = os.path.join(target_workdir, 'ivy.xml')
    jars, excludes = self._calculate_classpath(targets)
    self._generate_ivy(jars, excludes, ivyxml)

    ivy_args = ['-ivy', ivyxml]
    if LogOptions.stderr_log_level() == logging.DEBUG:
      ivy_args.append('-verbose')
    ivy_args.extend(args)
    if not self._transitive:
      ivy_args.append('-notransitive')
    ivy_args.extend(self._ivy_args)

    try:
      ivy = self._ivy_bootstrapper.ivy(self.java_executor)
      ivy.execute(ivy_args, jvm_args=self._jvm_args)
    except (Bootstrapper.Error, Ivy.Error) as e:
      raise TaskError('Failed to execute ivy call! %s' % e)
