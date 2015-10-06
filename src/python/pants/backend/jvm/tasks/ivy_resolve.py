# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import time
from textwrap import dedent

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.binaries import binary_util
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.strutil import safe_shlex_split


class IvyResolve(IvyTaskMixin, NailgunTask):

  @classmethod
  def register_options(cls, register):
    super(IvyResolve, cls).register_options(register)
    register('--override', action='append',
             fingerprint=True,
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
             fingerprint=True,
             help='Pass these extra args to ivy.')
    register('--confs', action='append', default=['default'],
             help='Pass a configuration to ivy in addition to the default ones.')
    register('--mutable-pattern',
             fingerprint=True,
             help='If specified, all artifact revisions matching this pattern will be treated as '
                  'mutable unless a matching artifact explicitly marks mutable as False.')
    cls.register_jvm_tool(register,
                          'xalan',
                          classpath=[
                            JarDependency(org='xalan', name='xalan', rev='2.7.1'),
                          ])

  @classmethod
  def product_types(cls):
    # TODO(John Sirois): These products support `IdeGen` and `Resolve` signalling their resolve
    # confs needs (via the 'jar_map_[conf suffix]'). Fix those tasks to do their own resolves.
    # See: https://github.com/pantsbuild/pants/issues/2177
    hack_product_signals = ['jar_map_default',
                            'jar_map_sources',
                            'jar_map_javadoc']

    return ['compile_classpath'] + hack_product_signals

  @classmethod
  def prepare(cls, options, round_manager):
    super(IvyResolve, cls).prepare(options, round_manager)
    round_manager.require_data('java')
    round_manager.require_data('scala')

  def __init__(self, *args, **kwargs):
    super(IvyResolve, self).__init__(*args, **kwargs)

    self._outdir = self.get_options().outdir or os.path.join(self.workdir, 'reports')
    self._open = self.get_options().open
    self._report = self._open or self.get_options().report

    self._args = []
    for arg in self.get_options().args:
      self._args.extend(safe_shlex_split(arg))

  @memoized_property
  def confs(self):
    # TODO(John Sirois): This supports `IdeGen` and `Resolve` signalling their resolve confs needs.
    # Fix those tasks to do their own resolves.
    # See: https://github.com/pantsbuild/pants/issues/2177
    confs = set(self.get_options().confs)
    for conf in ('default', 'sources', 'javadoc'):
      if self.context.products.isrequired('jar_map_{conf}'.format(conf=conf)):
        confs.add(conf)
    return confs

  def execute(self):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """
    executor = self.create_java_executor()
    targets = self.context.targets()
    compile_classpath = self.context.products.get_data('compile_classpath',
                                                       init_func=ClasspathProducts)
    resolve_hash_name = self.resolve(executor=executor,
                                     targets=targets,
                                     classpath_products=compile_classpath,
                                     confs=self.confs,
                                     extra_args=self._args)
    if self._report:
      self._generate_ivy_report(resolve_hash_name)

  def check_artifact_cache_for(self, invalidation_check):
    # Ivy resolution is an output dependent on the entire target set, and is not divisible
    # by target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]

  def _generate_ivy_report(self, resolve_hash_name):
    def make_empty_report(report, organisation, module, conf):
      no_deps_xml_template = dedent("""<?xml version="1.0" encoding="UTF-8"?>
        <?xml-stylesheet type="text/xsl" href="ivy-report.xsl"?>
        <ivy-report version="1.0">
          <info
            organisation="{organisation}"
            module="{module}"
            revision="latest.integration"
            conf="{conf}"
            confs="{conf}"
            date="{timestamp}"/>
        </ivy-report>
        """).format(
        organisation=organisation,
        module=module,
        conf=conf,
        timestamp=time.strftime('%Y%m%d%H%M%S'),
        )
      with open(report, 'w') as report_handle:
        print(no_deps_xml_template, file=report_handle)

    tool_classpath = self.tool_classpath('xalan')

    report = None
    org = IvyUtils.INTERNAL_ORG_NAME
    name = resolve_hash_name
    xsl = os.path.join(self.ivy_cache_dir, 'ivy-report.xsl')

    # Xalan needs this dir to exist - ensure that, but do no more - we have no clue where this
    # points.
    safe_mkdir(self._outdir, clean=False)

    for conf in self.confs:
      xml_path = self._get_report_path(conf, resolve_hash_name)
      if not os.path.exists(xml_path):
        # Make it clear that this is not the original report from Ivy by changing its name.
        xml_path = xml_path[:-4] + "-empty.xml"
        make_empty_report(xml_path, org, name, conf)
      out = os.path.join(self._outdir,
                         '{org}-{name}-{conf}.html'.format(org=org, name=name, conf=conf))
      args = ['-IN', xml_path, '-XSL', xsl, '-OUT', out]

      # The ivy-report.xsl genrates tab links to files with extension 'xml' by default, we
      # override that to point to the html files we generate.
      args.extend(['-param', 'extension', 'html'])

      if 0 != self.runjava(classpath=tool_classpath, main='org.apache.xalan.xslt.Process',
                           args=args, workunit_name='report'):
        raise self.Error('Failed to create html report from xml ivy report.')

      # The ivy-report.xsl is already smart enough to generate an html page with tab links to all
      # confs for a given report coordinate (org, name).  We need only display 1 of the generated
      # htmls and the user can then navigate to the others via the tab links.
      if report is None:
        report = out

    css = os.path.join(self._outdir, 'ivy-report.css')
    if os.path.exists(css):
      os.unlink(css)
    shutil.copy(os.path.join(self.ivy_cache_dir, 'ivy-report.css'), self._outdir)

    if self._open and report:
      binary_util.ui_open(report)

  def _get_report_path(self, conf, resolve_hash_name):
    try:
      return IvyUtils.xml_report_path(self.ivy_cache_dir, resolve_hash_name, conf)
    except IvyUtils.IvyResolveReportError as e:
      raise self.Error('Failed to generate ivy report: {}'.format(e))
