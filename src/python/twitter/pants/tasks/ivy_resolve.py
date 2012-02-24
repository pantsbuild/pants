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
from contextlib import contextmanager

__author__ = 'John Sirois'

import os
import pkgutil
import re
import shutil

from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants import get_buildroot, is_internal, is_jvm
from twitter.pants.base.generator import Generator, TemplateData
from twitter.pants.tasks import binary_utils, TaskError
from twitter.pants.tasks.nailgun_task import NailgunTask

try:
  from lxml import etree
  _REPORT_AVAILABLE=True
except ImportError:
  _REPORT_AVAILABLE=False

class IvyResolve(NailgunTask):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    flag = mkflag('override')
    option_group.add_option(flag, action='append', dest='ivy_resolve_overrides',
                            help='''Specifies a jar dependency override in the form:
                            [org]#[name]=(revision|url)

                            For example, to specify 2 overrides:
                            %(flag)s=com.foo#bar=0.1.2 \\
                            %(flag)s=com.baz#spam=file:///tmp/spam.jar
                            ''' % dict(flag=flag))

    if _REPORT_AVAILABLE:
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

  def __init__(self, context,
               workdir=None,
               ivy_jar=None,
               ivy_settings=None,
               cache_dir=None,
               confs = None,
               transitive=None):

    classpath = [ivy_jar] if ivy_jar else context.config.getlist('ivy', 'classpath')
    nailgun_dir = context.config.get('ivy-resolve', 'nailgun_dir')
    NailgunTask.__init__(self, context, classpath=classpath, workdir=nailgun_dir)

    self._ivy_settings = ivy_settings or context.config.get('ivy', 'ivy_settings')
    self._cachedir = cache_dir or context.config.get('ivy-resolve', 'cache_dir')
    self._confs = confs or context.config.getlist('ivy-resolve', 'confs')
    self._transitive = transitive or context.config.getbool('ivy-resolve', 'transitive')
    self._args = confs or context.config.getlist('ivy-resolve', 'args')

    self._template_path = os.path.join('ivy_resolve', 'ivy.mk')

    work_dir = workdir or context.config.get('ivy-resolve', 'workdir')
    self._ivy_xml = os.path.join(work_dir, 'ivy.xml')
    self._classpath_file = os.path.join(work_dir, 'classpath')
    self._classpath_dir = os.path.join(work_dir, 'mapped')

    if _REPORT_AVAILABLE:
      self._outdir = context.options.ivy_resolve_outdir or os.path.join(work_dir, 'reports')
      self._open = context.options.ivy_resolve_open
      self._report = self._open or context.options.ivy_resolve_report
    else:
      self._report = False

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

    def is_classpath(t):
      return is_internal(t) and any(jar for jar in t.jar_dependencies if jar.rev)

    with self.changed(filter(is_classpath, targets), only_buildfiles=True) as changed_deps:
      if changed_deps:
        self._ivycachepath(self._ivy_xml, self._classpath_file, *targets)

    if os.path.exists(self._classpath_file):
      with self._cachepath(self._classpath_file) as classpath:
        with self.context.state('classpath', []) as cp:
          for path in classpath:
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
    org, name = self._identify()
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
    org, name = self._identify()
    with open(os.path.join(self._cachedir, 'ivy-report.xsl')) as report_xsl:
      xsltree = etree.parse(report_xsl)
      transform = etree.XSLT(xsltree)
      reports = []
      for conf in self._confs:
        report_name = '%s-%s-%s.xml' % (org, name, conf)
        with open(os.path.join(self._cachedir, report_name)) as report_xml:
          xmltree = etree.parse(report_xml)
          html_name = '%s-%s-%s.html' % (org, name, conf)
          with safe_open(os.path.join(self._outdir, html_name), 'w') as report_html:
            html_content = str(transform(xmltree))
            report_html.write(html_content)
            reports.append(report_html.name)

      css = os.path.join(self._outdir, 'ivy-report.css')
      if os.path.exists(css):
        os.unlink(css)
      shutil.copy(os.path.join(self._cachedir, 'ivy-report.css'), self._outdir)

      if self._open:
        binary_utils.open(*reports)

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
    ivyxml = os.path.join(self._classpath_dir, '%s.ivy.xml' % target.id)
    classpathfile = os.path.join(self._classpath_dir, '%s.classpath' % target.id)
    self._ivycachepath(ivyxml, classpathfile, target)

    with self._cachepath(classpathfile) as classpath:
      for path in classpath:
        dir, jar = os.path.split(path.strip())
        genmap.add(target, dir).append(jar)

  def _ivycachepath(self, ivyxml, classpathfile, *targets):
    jars, excludes = self._calculate_classpath(targets)
    self._generate_ivy(jars, excludes, ivyxml)

    ivy_args = [
      '-settings', self._ivy_settings,
      '-cache', self._cachedir,
      '-ivy', ivyxml,
      '-types', 'jar',
      '-cachepath', classpathfile,
      '-confs'
    ]
    ivy_args.extend(self._confs)
    if not self._transitive:
      ivy_args.append('-notransitive')
    ivy_args.extend(self._args)

    safe_mkdir(os.path.dirname(classpathfile))
    result = self.ng('org.apache.ivy.Main', *ivy_args)
    if result != 0:
      raise TaskError('org.apache.ivy.Main returned %d' % result)
