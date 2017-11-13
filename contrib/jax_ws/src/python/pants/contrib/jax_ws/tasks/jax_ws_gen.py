# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.distribution.distribution import DistributionLocator
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.process_handler import subprocess

from pants.contrib.jax_ws.targets.jax_ws_library import JaxWsLibrary

logger = logging.getLogger(__name__)


class JaxWsGen(SimpleCodegenTask, NailgunTask):
  """Generates Java files from wsdl files using the JAX-WS compiler."""

  @classmethod
  def register_options(cls, register):
    super(JaxWsGen, cls).register_options(register)
    register('--ws-quiet', type=bool, help='Suppress WsImport output')
    register('--ws-verbose', type=bool, help='Make WsImport output verbose')

  @classmethod
  def subsystem_dependencies(cls):
    return super(JaxWsGen, cls).subsystem_dependencies() + (DistributionLocator,)

  def __init__(self, *args, **kwargs):
    super(JaxWsGen, self).__init__(*args, **kwargs)

  def synthetic_target_type(self, target):
    return JavaLibrary

  def is_gentarget(self, target):
    return isinstance(target, JaxWsLibrary)

  @classmethod
  def supported_strategy_types(cls):
    return [cls.IsolatedCodegenStrategy]

  def execute_codegen(self, target, target_workdir):
    wsdl_directory = target.payload.sources.rel_path
    for source in target.payload.sources.source_paths:
      url = os.path.join(wsdl_directory, source)
      wsimport_cmd = self._build_wsimport_cmd(target, target_workdir, url)
      with self.context.new_workunit(name='wsimport',
                                     cmd=' '.join(wsimport_cmd),
                                     labels=[WorkUnitLabel.TOOL]) as workunit:
        self.context.log.debug('Executing {}'.format(' '.join(wsimport_cmd)))
        return_code = subprocess.Popen(wsimport_cmd,
                                       stdout=workunit.output('stdout'),
                                       stderr=workunit.output('stderr')).wait()
        workunit.set_outcome(WorkUnit.FAILURE if return_code else WorkUnit.SUCCESS)
        if return_code:
          raise TaskError('wsimport exited non-zero {rc}'.format(rc=return_code))

  def _build_wsimport_cmd(self, target, target_workdir, url):
    distribution = DistributionLocator.cached(jdk=True)
    # Ported and trimmed down from:
    # https://java.net/projects/jax-ws-commons/sources/svn/content/trunk/
    # jaxws-maven-plugin/src/main/java/org/jvnet/jax_ws_commons/jaxws/WsImportMojo.java?rev=1191
    cmd = ['{}/bin/wsimport'.format(distribution.real_home)]
    if self.get_options().ws_verbose:
      cmd.append('-verbose')
    if self.get_options().ws_quiet:
      cmd.append('-quiet')
    cmd.append('-Xnocompile') # Always let pants do the compiling work.
    cmd.extend(['-keep', '-s', os.path.abspath(target_workdir)])
    cmd.extend(['-d', os.path.abspath(target_workdir)])
    if target.payload.xjc_args:
      cmd.extend(('-B{}'.format(a) if a.startswith('-') else a) for a in target.payload.xjc_args)
    cmd.append('-B-no-header') # Don't let xjc write out a timestamp, because it'll break caching.
    cmd.extend(target.payload.extra_args)
    cmd.append(url)
    if self.get_options().level == 'debug':
      cmd.append('-Xdebug')
    return cmd

  @property
  def _copy_target_attributes(self):
    """Propagate the provides attribute to the synthetic java_library() target for publishing."""
    return ['provides']
