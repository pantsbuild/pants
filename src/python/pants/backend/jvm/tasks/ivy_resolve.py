# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import shutil
import time

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
  def setup_parser(cls, option_group, args, mkflag):
    super(IvyResolve, cls).setup_parser(option_group, args, mkflag)

    flag = mkflag('override')
    option_group.add_option(flag, action='append', dest='ivy_resolve_overrides',
                            help="""Specifies a jar dependency override in the form:
                            [org]#[name]=(revision|url)

                            For example, to specify 2 overrides:
                            %(flag)s=com.foo#bar=0.1.2 \\
                            %(flag)s=com.baz#spam=file:///tmp/spam.jar
                            """ % dict(flag=flag))

    report = mkflag("report")
    option_group.add_option(report, mkflag("report", negate=True), dest="ivy_resolve_report",
                            action="callback", callback=mkflag.set_bool, default=False,
                            help="[%default] Generate an ivy resolve html report")

    option_group.add_option(mkflag("open"), mkflag("open", negate=True),
                            dest="ivy_resolve_open", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%%default] Attempt to open the generated ivy resolve report "
                                 "in a browser (implies %s)." % report)

    option_group.add_option(mkflag("outdir"), dest="ivy_resolve_outdir",
                            help="Emit ivy report outputs in to this directory.")

    option_group.add_option(mkflag("args"), dest="ivy_args", action="append", default=[],
                            help="Pass these extra args to ivy.")

    option_group.add_option(mkflag("mutable-pattern"), dest="ivy_mutable_pattern",
                            help="If specified, all artifact revisions matching this pattern will "
                                 "be treated as mutable unless a matching artifact explicitly "
                                 "marks mutable as False.")

  @classmethod
  def product_types(cls):
    return ['ivy_jar_products', 'jar_dependencies']

  def __init__(self, *args, **kwargs):
    super(IvyResolve, self).__init__(*args, **kwargs)

    self._ivy_bootstrapper = Bootstrapper.instance()
    self._cachedir = self._ivy_bootstrapper.ivy_cache_dir
    self._confs = self.context.config.getlist(self._CONFIG_SECTION, 'confs', default=['default'])
    self._classpath_dir = os.path.join(self.workdir, 'mapped')

    self._outdir = self.context.options.ivy_resolve_outdir or os.path.join(self.workdir, 'reports')
    self._open = self.context.options.ivy_resolve_open
    self._report = self._open or self.context.options.ivy_resolve_report

    self._ivy_bootstrap_key = 'ivy'
    ivy_bootstrap_tools = self.context.config.getlist(self._CONFIG_SECTION,
                                                      'bootstrap-tools', ':xalan')
    self.register_jvm_tool(self._ivy_bootstrap_key, ivy_bootstrap_tools)

    self._ivy_utils = IvyUtils(config=self.context.config,
                               options=self.context.options,
                               log=self.context.log)

    # Typically this should be a local cache only, since classpaths aren't portable.
    self.setup_artifact_cache_from_config(config_section=self._CONFIG_SECTION)

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    round_manager.require_data('exclusives_groups')

  def execute(self):
    """Resolves the specified confs for the configured targets and returns an iterator over
    tuples of (conf, jar path).
    """

    groups = self.context.products.get_data('exclusives_groups')
    executor = self.create_java_executor()
    targets = self.context.targets()

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
                                   executor=executor,
                                   symlink_ivyxml=True,
                                   workunit_name='ivy-resolve')
      if self.context.products.is_required_data('ivy_jar_products'):
        self._populate_ivy_jar_products(group_targets)
      for conf in self._confs:
        # It's important we add the full classpath as an (ordered) unit for code that is classpath
        # order sensitive
        classpath_entries = map(lambda entry: (conf, entry), classpath)
        groups.update_compatible_classpaths(group_key, classpath_entries)

      if self._report:
        self._generate_ivy_report(group_targets)

    # TODO(ity): populate a Classpath object instead of mutating exclusives_groups
    create_jardeps_for = self.context.products.isrequired('jar_dependencies')
    if create_jardeps_for:
      genmap = self.context.products.get('jar_dependencies')
      for target in filter(create_jardeps_for, targets):
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
      ivyinfo = self._ivy_utils.parse_xml_report(targets, conf)
      if ivyinfo:
        # Value is a list, to accommodate multiple exclusives groups.
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

    classpath = self.tool_classpath(self._ivy_bootstrap_key, self.create_java_executor())

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
      if 0 != self.runjava(classpath=classpath, main='org.apache.xalan.xslt.Process',
                           args=args, workunit_name='report'):
        raise TaskError
      reports.append(out)

    css = os.path.join(self._outdir, 'ivy-report.css')
    if os.path.exists(css):
      os.unlink(css)
    shutil.copy(os.path.join(self._cachedir, 'ivy-report.css'), self._outdir)

    if self._open:
      binary_util.ui_open(*reports)
