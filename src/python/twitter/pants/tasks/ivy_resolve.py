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
from twitter.pants.targets.jar_dependency import JarDependency

__author__ = 'John Sirois'

import hashlib
import os
import pkgutil
import re
import shutil

from contextlib import contextmanager

from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants import get_buildroot, is_internal, is_jvm
from twitter.pants.base.generator import Generator, TemplateData
from twitter.pants.tasks import binary_utils, TaskError
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

  def __init__(self, context):
    classpath = context.config.getlist('ivy', 'classpath')
    nailgun_dir = context.config.get('ivy-resolve', 'nailgun_dir')
    NailgunTask.__init__(self, context, classpath=classpath, workdir=nailgun_dir)

    self._ivy_settings = context.config.get('ivy', 'ivy_settings')
    self._cachedir = context.config.get('ivy', 'cache_dir')
    self._confs = context.config.getlist('ivy-resolve', 'confs')
    self._transitive = context.config.getbool('ivy-resolve', 'transitive')
    self._args = context.config.getlist('ivy-resolve', 'args')

    self._profile = context.config.get('ivy-resolve', 'profile')

    self._template_path = os.path.join('ivy_resolve', 'ivy.mk')

    self._work_dir = context.config.get('ivy-resolve', 'workdir')
    self._classpath_file = os.path.join(self._work_dir, 'classpath')
    self._classpath_dir = os.path.join(self._work_dir, 'mapped')

    self._outdir = context.options.ivy_resolve_outdir or os.path.join(self._work_dir, 'reports')
    self._open = context.options.ivy_resolve_open
    self._report = self._open or context.options.ivy_resolve_report
    self._ivy_utils = IvyUtils(context, self._cachedir)

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
    """
      Resolves the specified confs for the configured targets and returns an iterator over tuples
      of (conf, jar path).
    """

    def dirname_for_requested_targets(targets):
      """Where we put the classpath file for this set of targets."""
      sha = hashlib.sha1()
      for t in targets:
        sha.update(t.id)
      return sha.hexdigest()

    def is_classpath(t):
      return is_internal(t) and any(jar for jar in t.jar_dependencies if jar.rev)

    classpath_targets = filter(is_classpath, targets)
    target_workdir = os.path.join(self._work_dir, dirname_for_requested_targets(targets))
    target_classpath_file = os.path.join(target_workdir, 'classpath')
    with self.invalidated(classpath_targets, only_buildfiles=True, invalidate_dependants=True) as invalidated:
      # Note that it's possible for all targets to be valid but for no classpath file to exist at
      # target_classpath_file, e.g., if we previously build a superset of targets.
      if invalidated.invalid_targets() or not os.path.exists(target_classpath_file):
        self._exec_ivy(target_workdir, targets, [
          '-cachepath', target_classpath_file,
          '-confs'
        ] + self._confs)

    if not os.path.exists(target_classpath_file):
      raise TaskError, 'Ivy failed to create classpath file at %s' % target_classpath_file

    def safe_link(src, dest):
      if os.path.exists(dest):
        os.unlink(dest)
      os.symlink(src, dest)

    # Symlink to the current classpath file.
    safe_link(target_classpath_file, self._classpath_file)

    # Symlink to the current ivy.xml file (useful for IDEs that read it).
    ivyxml_symlink = os.path.join(self._work_dir, 'ivy.xml')
    target_ivyxml = os.path.join(target_workdir, 'ivy.xml')
    safe_link(target_ivyxml, ivyxml_symlink)

    with self._cachepath(self._classpath_file) as classpath:
      with self.context.state('classpath', []) as cp:
        for path in classpath:
          if self._is_jar(path):
            for conf in self._confs:
              cp.append((conf, path.strip()))

    if self._report:
      self._generate_ivy_report()

    create_jardeps_for = self.context.products.isrequired('jar_dependencies')
    if create_jardeps_for:
      genmap = self.context.products.get('jar_dependencies')
      for target in filter(create_jardeps_for, targets):
        self._mapjars(genmap, target)

  def _generate_ivy(self, jars, excludes, ivyxml):
    org, name = self._ivy_utils.identify()
    template_data = TemplateData(
      org=org,
      module=name,
      version='latest.integration',
      publications=None,
      dependencies=[self._generate_jar_template(jar) for jar in jars],
      excludes=[self._generate_exclude_template(exclude) for exclude in excludes]
    )

    safe_mkdir(os.path.dirname(ivyxml))
    with open(ivyxml, 'w') as output:
      generator = Generator(pkgutil.get_data(__name__, self._template_path),
                            root_dir = get_buildroot(),
                            lib = template_data)
      generator.write(output)

  def _generate_ivy_report(self):
    classpath = binary_utils.nailgun_profile_classpath(self, self._profile)

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
      xml = self._ivy_utils.xml_report_path(conf)
      out = os.path.join(self._outdir, '%(org)s-%(name)s-%(conf)s.html' % params)
      args = ['-IN', xml, '-XSL', xsl, '-OUT', out]
      self.runjava('org.apache.xalan.xslt.Process', classpath=classpath, args=args)
      reports.append(out)

    css = os.path.join(self._outdir, 'ivy-report.css')
    if os.path.exists(css):
      os.unlink(css)
    shutil.copy(os.path.join(self._cachedir, 'ivy-report.css'), self._outdir)

    if self._open:
      binary_utils.open(*reports)

  def _calculate_classpath(self, targets):
    jars = set()
    excludes = set()
    def collect_jars(target):
      if target.jar_dependencies:
        jars.update(jar for jar in target.jar_dependencies if jar.rev)
      if target.excludes:
        excludes.update(target.excludes)
    for target in targets:
      target.walk(collect_jars, is_jvm)
    return jars, excludes

  def _generate_jar_template(self, jar):
    template = TemplateData(
      org = jar.org,
      module = jar.name,
      version = jar.rev,
      force = jar.force,
      excludes = [self._generate_exclude_template(exclude) for exclude in jar.excludes],
      transitive = jar.transitive,
      ext = jar.ext,
      url = jar.url,
      configurations = ';'.join(jar._configurations),
    )
    override = self._overrides.get((jar.org, jar.name))
    return override(template) if override else template

  def _generate_exclude_template(self, exclude):
    return TemplateData(org = exclude.org, name = exclude.name)

  @contextmanager
  def _cachepath(self, file):
    with safe_open(file, 'r') as cp:
      yield (path.strip() for path in cp.read().split(os.pathsep) if path.strip())

  def _mapjars(self, genmap, target):
    mapdir = os.path.join(self._classpath_dir, target.id)
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
                if self._is_jar(file):
                  # TODO(John Sirois): kill the org and (org, name) exclude mappings in favor of a
                  # conf whitelist
                  genmap.add(org, confdir).append(file)
                  genmap.add((org, name), confdir).append(file)

                  genmap.add(target, confdir).append(file)
                  genmap.add((target, conf), confdir).append(file)
                  genmap.add((org, name, conf), confdir).append(file)

  def _is_jar(self, path):
    return path.endswith('.jar')

  def _exec_ivy(self, target_workdir, targets, args):
    ivyxml = os.path.join(target_workdir, 'ivy.xml')
    jars, excludes = self._calculate_classpath(targets)
    self._generate_ivy(jars, excludes, ivyxml)

    ivy_args = [
      '-settings', self._ivy_settings,
      '-cache', self._cachedir,
      '-ivy', ivyxml,
    ]
    ivy_args.extend(args)
    if not self._transitive:
      ivy_args.append('-notransitive')
    ivy_args.extend(self._args)

    result = self.runjava('org.apache.ivy.Main', args=ivy_args)
    if result != 0:
      raise TaskError('org.apache.ivy.Main returned %d' % result)

