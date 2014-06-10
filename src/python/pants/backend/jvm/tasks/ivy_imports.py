# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import shutil
import time

from twitter.common.dirutil import safe_mkdir

from pants import binary_util
from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.fs.source_util import get_archive_root
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy import Ivy
from pants.java import util


class IvyImports(NailgunTask, IvyTaskMixin, JvmToolTaskMixin):
  """Resolves jar source imports (currently only used by java_protobuf_library)."""
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(IvyImports, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("args"), dest="ivy_args", action="append", default=[],
                            help="Pass these extra args to ivy.")


  def __init__(self, context, workdir, confs=None):
    super(IvyImports, self).__init__(context, workdir)
    # Mostly copy-pastad from ivy_resolve.py; perhaps some of this is obsolete?
    self._ivy_bootstrapper = Bootstrapper.instance()
    self._cachedir = self._ivy_bootstrapper.ivy_cache_dir
    self._confs = confs or context.config.getlist('ivy-resolve', 'confs', default=['default'])
    self._classpath_dir = os.path.join(self.workdir, 'mapped')

    self._outdir = context.options.ivy_resolve_outdir or os.path.join(self.workdir, 'reports')
    self._open = context.options.ivy_resolve_open

    self._ivy_bootstrap_key = 'ivy'
    ivy_bootstrap_tools = context.config.getlist('ivy-resolve', 'bootstrap-tools', ':xalan')
    self.register_jvm_tool(self._ivy_bootstrap_key, ivy_bootstrap_tools)

    self._ivy_utils = IvyUtils(config=context.config,
                               options=context.options,
                               log=context.log)

    # Typically this should be a local cache only, since classpaths aren't portable.
    self.setup_artifact_cache_from_config(config_section='ivy-resolve')

  def invalidate_for(self):
    return self.context.options.ivy_resolve_overrides

  def execute(self):
    """Resolves the import_jars for any protobuf libraries in the context's targets."""
    executor = self.create_java_executor()
    targets = self.context.targets()

    # Vastly simplified from ivy_resolve, due to very restricted use (protobuf headers, basically)
    group_targets = set(filter(lambda t: t.has_label('has_imports'), targets))

    # NOTE(pl): The symlinked ivy.xml (for IDEs, particularly IntelliJ) in the presence of multiple
    # exclusives groups will end up as the last exclusives group run.  I'd like to deprecate this
    # eventually, but some people rely on it, and it's not clear to me right now whether telling
    # them to use IdeaGen instead is feasible.
    classpath = self.ivy_resolve(group_targets,
                                 executor=executor,
                                 symlink_ivyxml=True,
                                 workunit_name='ivy-resolve')

    for conf in self._confs:
      # It's important we add the full classpath as an (ordered) unit for code that is classpath
      # order sensitive
      classpath_entries = map(lambda entry: (conf, entry), classpath)

    genmap = {}
    for target in group_targets:
      self._ivy_proto(target, executor=executor,
                              workunit_factory=self.context.new_workunit)

  def _ivy_proto(self, target, executor, workunit_factory):
    """Resolves the import_jars in target."""
    mapdir = get_archive_root()
    safe_mkdir(mapdir, clean=False)
    ivyargs = [
      '-retrieve', '%s/[organisation]/[artifact]/jars/'
                   '[artifact]-[revision].[ext]' % mapdir,
      '-symlink',
    ]

    def exec_ivy(target_workdir,
                 targets,
                 args,
                 confs=None,
                 ivy=None,
                 workunit_name='ivy',
                 workunit_factory=None,
                 symlink_ivyxml=False):
      ivy = ivy or Bootstrapper.default_ivy()
      if not isinstance(ivy, Ivy):
        raise ValueError('The ivy argument supplied must be an Ivy instance, given %s of type %s'
                         % (ivy, type(ivy)))

      ivyxml = os.path.join(target_workdir, 'ivy.xml')
      # Combine all targets' import_jars into one set
      jars = reduce(lambda a,b: a^b, (t.import_jars(self.context) for t in targets), set())
      excludes = set()

      ivy_args = ['-ivy', ivyxml]

      confs_to_resolve = confs or ['default']
      ivy_args.append('-confs')
      ivy_args.extend(confs_to_resolve)

      ivy_args.extend(args)
      ivy_args.append('-notransitive') # always intransitive
      ivy_args.extend(self._ivy_utils._args)

      def safe_link(src, dest):
        if os.path.exists(dest):
          os.unlink(dest)
        os.symlink(src, dest)

      with IvyUtils.ivy_lock:
        self._ivy_utils._generate_ivy(targets, jars, excludes, ivyxml, confs_to_resolve)
        runner = ivy.runner(jvm_options=self._ivy_utils._jvm_options, args=ivy_args)
        try:
          result = util.execute_runner(runner,
                                       workunit_factory=workunit_factory,
                                       workunit_name=workunit_name)

          # Symlink to the current ivy.xml file (useful for IDEs that read it).
          if symlink_ivyxml:
            ivyxml_symlink = os.path.join(self._ivy_utils._workdir, 'ivy.xml')
            safe_link(ivyxml, ivyxml_symlink)

          if result != 0:
            raise TaskError('Ivy returned %d' % result)
        except runner.executor.Error as e:
          raise TaskError(e)

    exec_ivy(mapdir,
             [target],
             ivyargs,
             confs=target.payload.configurations,
             ivy=Bootstrapper.default_ivy(executor),
             workunit_factory=workunit_factory,
             workunit_name='map-import-jars')


  def check_artifact_cache_for(self, invalidation_check):
    # Ivy resolution is an output dependent on the entire target set, and is not divisible by
    # target. So we can only cache it keyed by the entire target set.
    global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
    return [global_vts]
