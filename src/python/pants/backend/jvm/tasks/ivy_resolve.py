# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import shutil
import time

from twitter.common.collections import OrderedSet

from pants import binary_util
from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.ivy.bootstrapper import Bootstrapper
from pants.util.dirutil import safe_mkdir


class IvyResolve(NailgunTask, IvyTaskMixin, JvmToolTaskMixin):
  _CONFIG_SECTION = 'ivy-resolve'

  @classmethod
  def register_options(cls, register):
    super(IvyResolve, cls).register_options(register)
    register('--override', action='append',
             help='Specifies a jar dependency override in the form: '
             '[org]#[name]=(revision|url) '
             'Multiple overrides can be specified using repeated invocations of this flag. '
             'For example, to specify 2 overrides: '
             '--override=com.foo#bar=0.1.2 '
             '--override=com.baz#spam=file:///tmp/spam.jar ')
    register('--report', action='store_true', default=False,
             help='Generate an ivy resolve html report')
    register('--open', action='store_true', default=False,
             help='Attempt to open the generated ivy resolve report '
                  'in a browser (implies --report)')
    register('--outdir', help='Emit ivy report outputs in to this directory.')
    register('--args', action='append',
             help='Pass these extra args to ivy.')
    register('--mutable-pattern',
             help='If specified, all artifact revisions matching this pattern will be treated as '
                  'mutable unless a matching artifact explicitly marks mutable as False.')
    cls.register_jvm_tool(register, 'xalan')

  @classmethod
  def product_types(cls):
    return ['compile_classpath', 'ivy_jar_products', 'jar_dependencies']

  def __init__(self, *args, **kwargs):
    super(IvyResolve, self).__init__(*args, **kwargs)

    self._ivy_bootstrapper = Bootstrapper.instance()
    self._cachedir = self._ivy_bootstrapper.ivy_cache_dir
    self._confs = self.context.config.getlist(self._CONFIG_SECTION, 'confs', default=['default'])
    self._classpath_dir = os.path.join(self.workdir, 'mapped')

    self._outdir = self.get_options().outdir or os.path.join(self.workdir, 'reports')
    self._open = self.get_options().open
    self._report = self._open or self.get_options().report

    self._ivy_utils = IvyUtils(config=self.context.config, log=self.context.log)

    # Typically this should be a local cache only, since classpaths aren't portable.
    self.setup_artifact_cache()

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    round_manager.require_data('java')
    round_manager.require_data('scala')

  def execute(self):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """

    executor = self.create_java_executor()
    targets = self.context.targets()
    compile_classpath = self.context.products.get_data('compile_classpath',
                                                       lambda: OrderedSet())

    # After running ivy, we need to take the resulting classpath, and load it into
    # the build products.
    ivy_classpath = self.ivy_resolve(targets,
                                 executor=executor,
                                 symlink_ivyxml=True,
                                 workunit_name='ivy-resolve')
    if self.context.products.is_required_data('ivy_jar_products'):
      self._populate_ivy_jar_products(targets)
    for conf in self._confs:
      # It's important we add the full classpath as an (ordered) unit for code that is classpath
      # order sensitive
      compile_classpath.update(map(lambda entry: (conf, entry), ivy_classpath))

    if self._report:
      self._generate_ivy_report(targets)

    create_jardeps_for = self.context.products.isrequired('jar_dependencies')
    if create_jardeps_for:
      genmap = self.context.products.get('jar_dependencies')
      for target in filter(create_jardeps_for, targets):
        # TODO: Add mapjars to IvyTaskMixin? Or get rid of the mixin? It's weird that we use
        # self.ivy_resolve for some ivy invocations but this for others.
        self._ivy_utils.mapjars(genmap, target, executor=executor,
                                workunit_factory=self.context.new_workunit)

  def check_artifact_cache_for(self, invalidation_check):
    # Ivy resolution is an output dependent on the entire target set, and is not divisible
    # by target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]

  def _populate_ivy_jar_products(self, targets):
    """Populate the build products with an IvyInfo object for each generated ivy report."""
    ivy_products = self.context.products.get_data('ivy_jar_products') or defaultdict(list)
    for conf in self._confs:
      ivyinfo = IvyUtils.parse_xml_report(targets, conf)
      if ivyinfo:
        # TODO(stuhood): Value is a list, previously to accommodate multiple exclusives groups.
        ivy_products[conf].append(ivyinfo)
    self.context.products.safe_create_data('ivy_jar_products', lambda: ivy_products)

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

    tool_classpath = self.tool_classpath('xalan', executor=self.create_java_executor())

    reports = []
    org, name = IvyUtils.identify(targets)
    xsl = os.path.join(self._cachedir, 'ivy-report.xsl')

    # Xalan needs this dir to exist - ensure that, but do no more - we have no clue where this
    # points.
    safe_mkdir(self._outdir, clean=False)

    for conf in self._confs:
      params = dict(org=org, name=name, conf=conf)
      xml = IvyUtils.xml_report_path(targets, conf)
      if not os.path.exists(xml):
        make_empty_report(xml, org, name, conf)
      out = os.path.join(self._outdir, '%(org)s-%(name)s-%(conf)s.html' % params)
      args = ['-IN', xml, '-XSL', xsl, '-OUT', out]
      if 0 != self.runjava(classpath=tool_classpath, main='org.apache.xalan.xslt.Process',
                           args=args, workunit_name='report'):
        raise TaskError
      reports.append(out)

    css = os.path.join(self._outdir, 'ivy-report.css')
    if os.path.exists(css):
      os.unlink(css)
    shutil.copy(os.path.join(self._cachedir, 'ivy-report.css'), self._outdir)

    if self._open:
      binary_util.ui_open(*reports)
