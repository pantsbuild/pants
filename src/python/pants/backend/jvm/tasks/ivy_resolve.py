# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import time
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants import binary_util
from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.goal.products import UnionProducts
from pants.ivy.bootstrapper import Bootstrapper
from pants.util.dirutil import safe_mkdir
from pants.util.strutil import safe_shlex_split


class IvyResolve(IvyTaskMixin, NailgunTask, JvmToolTaskMixin):
  _CONFIG_SECTION = 'ivy-resolve'

  class Error(TaskError):
    """Error in IvyResolve."""

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
    register('--confs', action='append', default=['default'],
             help='Pass a configuration to ivy in addition to the default ones.')
    register('--mutable-pattern',
             help='If specified, all artifact revisions matching this pattern will be treated as '
                  'mutable unless a matching artifact explicitly marks mutable as False.')
    cls.register_jvm_tool(register, 'xalan')

  @classmethod
  def product_types(cls):
    return [
        'compile_classpath',
        'ivy_cache_dir',
        'ivy_jar_products',
        'ivy_resolve_symlink_map',
        'jar_dependencies',
        'jar_map_default',
        'jar_map_sources',
        'jar_map_javadoc']

  @classmethod
  def prepare(cls, options, round_manager):
    super(IvyResolve, cls).prepare(options, round_manager)
    round_manager.require_data('java')
    round_manager.require_data('scala')

  def __init__(self, *args, **kwargs):
    super(IvyResolve, self).__init__(*args, **kwargs)

    self._ivy_bootstrapper = Bootstrapper.instance()
    self._cachedir = self._ivy_bootstrapper.ivy_cache_dir
    self._classpath_dir = os.path.join(self.workdir, 'mapped')
    self._outdir = self.get_options().outdir or os.path.join(self.workdir, 'reports')
    self._open = self.get_options().open
    self._report = self._open or self.get_options().report
    self._confs = None

    self._args = []
    for arg in self.get_options().args:
      self._args.extend(safe_shlex_split(arg))

    # Typically this should be a local cache only, since classpaths aren't portable.
    self.setup_artifact_cache()

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  @property
  def confs(self):
    if self._confs is None:
      self._confs = set(self.get_options().confs)
      for conf in ('default', 'sources', 'javadoc'):
        if self.context.products.isrequired('jar_map_{conf}'.format(conf=conf)):
          self._confs.add(conf)
    return self._confs

  def execute(self):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """

    executor = self.create_java_executor()
    targets = self.context.targets()
    self.context.products.safe_create_data('ivy_cache_dir', lambda: self._cachedir)
    compile_classpath = self.context.products.get_data('compile_classpath',
                                                       lambda: UnionProducts())

    # After running ivy, we parse the resulting report, and record the dependencies for
    # all relevant targets (ie: those that have directory dependencies).
    _, relevant_targets = self.ivy_resolve(
      targets,
      executor=executor,
      workunit_name='ivy-resolve',
      confs=self.confs,
      custom_args=self._args,
    )

    # Record the ordered subset of jars that each jar_library/leaf depends on using
    # stable symlinks within the working copy.
    ivy_jar_products = self._generate_ivy_jar_products(relevant_targets)
    symlink_map = self.context.products.get_data('ivy_resolve_symlink_map')
    for conf in self.confs:
      ivy_jar_memo = {}
      ivy_info = ivy_jar_products[conf]
      if not ivy_info:
        continue
      # TODO: refactor ivy_jar_products to remove list
      ivy_info = ivy_info[0]
      for target in relevant_targets:
        if not isinstance(target, JarLibrary):
          continue
        # Add the artifacts from each dependency module.
        artifact_paths = list()
        for module in ivy_info.get_modules_for_jar_library(target, memo=ivy_jar_memo):
          artifact_paths += map(lambda a: symlink_map[a.path][0], module.artifacts)
        compile_classpath.add_for_target(target, map(lambda entry: (conf, entry), artifact_paths))

    if self._report:
      self._generate_ivy_report(relevant_targets)
    if self.context.products.is_required_data('ivy_jar_products'):
      self._populate_ivy_jar_products(relevant_targets, ivy_jar_products)

    create_jardeps_for = self.context.products.isrequired('jar_dependencies')
    if create_jardeps_for:
      genmap = self.context.products.get('jar_dependencies')
      for target in filter(create_jardeps_for, targets):
        self.mapjars(genmap, target, executor=executor)

  def check_artifact_cache_for(self, invalidation_check):
    # Ivy resolution is an output dependent on the entire target set, and is not divisible
    # by target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]

  def _generate_ivy_jar_products(self, targets):
    """Based on the ivy report, compute a map of conf to lists of IvyInfo objects."""
    ivy_products = defaultdict(list)
    for conf in self.confs:
      ivyinfo = IvyUtils.parse_xml_report(targets, conf)
      if ivyinfo:
        # TODO(stuhood): Value is a list, previously to accommodate multiple exclusives groups.
        ivy_products[conf].append(ivyinfo)
    return ivy_products

  def _populate_ivy_jar_products(self, targets, new_ivy_products):
    """Merge the given info into the ivy_jar_products product."""
    ivy_products = self.context.products.get_data('ivy_jar_products', lambda: defaultdict(list))
    for conf, new_ivyinfos in new_ivy_products.items():
      ivy_products[conf] += new_ivyinfos

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

    tool_classpath = self.tool_classpath('xalan')

    report = None
    org, name = IvyUtils.identify(targets)
    xsl = os.path.join(self._cachedir, 'ivy-report.xsl')

    # Xalan needs this dir to exist - ensure that, but do no more - we have no clue where this
    # points.
    safe_mkdir(self._outdir, clean=False)

    for conf in self.confs:
      params = dict(org=org, name=name, conf=conf)
      xml = IvyUtils.xml_report_path(targets, conf)
      if not os.path.exists(xml):
        make_empty_report(xml, org, name, conf)
      out = os.path.join(self._outdir, '%(org)s-%(name)s-%(conf)s.html' % params)
      args = ['-IN', xml, '-XSL', xsl, '-OUT', out]

      # The ivy-report.xsl genrates tab links to files with extension 'xml' by default, we
      # override that to point to the html files we generate.
      args.extend(['-param', 'extension', 'html'])

      if 0 != self.runjava(classpath=tool_classpath, main='org.apache.xalan.xslt.Process',
                           args=args, workunit_name='report'):
        raise IvyResolve.Error('Failed to create html report from xml ivy report.')

      # The ivy-report.xsl is already smart enough to generate an html page with tab links to all
      # confs for a given report coordinate (org, name).  We need only display 1 of the generated
      # htmls and the user can then navigate to the others via the tab links.
      if report is None:
        report = out

    css = os.path.join(self._outdir, 'ivy-report.css')
    if os.path.exists(css):
      os.unlink(css)
    shutil.copy(os.path.join(self._cachedir, 'ivy-report.css'), self._outdir)

    if self._open and report:
      binary_util.ui_open(report)
