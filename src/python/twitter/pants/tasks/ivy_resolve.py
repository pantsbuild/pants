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
import shutil
import time

from contextlib import contextmanager

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants import binary_util, is_internal, is_jar, is_concrete
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

    self._cachedir = context.options.ivy_resolve_cache or context.config.get('ivy', 'cache_dir')
    self._confs = confs or context.config.getlist('ivy-resolve', 'confs')
    self._work_dir = context.config.get('ivy-resolve', 'workdir')
    self._classpath_dir = os.path.join(self._work_dir, 'mapped')

    self._outdir = context.options.ivy_resolve_outdir or os.path.join(self._work_dir, 'reports')
    self._open = context.options.ivy_resolve_open
    self._report = self._open or context.options.ivy_resolve_report

    self._ivy_bootstrap_tools = context.config.getlist('ivy-resolve', 'bootstrap-tools', ':xalan')
    self._bootstrap_utils.register_all([self._ivy_bootstrap_tools])

    self._ivy_utils = IvyUtils(config=context.config,
                               options=context.options,
                               log=context.log)
    context.products.require_data('exclusives_groups')

    # Typically this should be a local cache only, since classpaths aren't portable.
    artifact_cache_spec = context.config.getlist('ivy-resolve', 'artifact_caches', default=[])
    self.setup_artifact_cache(artifact_cache_spec)

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
      classpath = self.ivy_resolve(group_targets, self.runjava_indivisible)
      for conf in self._confs:
        for path in classpath:
          groups.update_compatible_classpaths(group_key, [(conf, path)])

    if self._report:
      self._generate_ivy_report()

    if self.context.products.isrequired('ivy_jar_products'):
      self._populate_ivy_jar_products(targets)

    create_jardeps_for = self.context.products.isrequired(self._ivy_utils._mapfor_typename())
    if create_jardeps_for:
      genmap = self.context.products.get(self._ivy_utils._mapfor_typename())
      for target in filter(create_jardeps_for, targets):
        self._ivy_utils.mapjars(genmap, target)

  def check_artifact_cache_for(self, invalidation_check):
    # Ivy resolution is an output dependent on the entire target set, and is not divisible
    # by target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]

  def _populate_ivy_jar_products(self, targets):
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
      ivyinfo = self._ivy_utils.parse_xml_report(targets, conf)
      if ivyinfo:
        genmap.add("ivy", conf, [ivyinfo])

  def _generate_ivy_report(self):
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

    classpath = self._bootstrap_utils.get_jvm_build_tools_classpath(self._ivy_bootstrap_tools,
                                                                    self.runjava_indivisible)

    reports = []
    org, name = self._ivy_utils.identify(self.context.target_roots)
    xsl = os.path.join(self._cachedir, 'ivy-report.xsl')
    safe_mkdir(self._outdir, clean=True)
    for conf in self._confs:
      params = dict(org=org, name=name, conf=conf)
      xml = os.path.join(self._cachedir, '%(org)s-%(name)s-%(conf)s.xml' % params)
      if not os.path.exists(xml):
        make_empty_report(xml, org, name, conf)
      #xml = self._ivy_utils.xml_report_path(self.context, conf)
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

