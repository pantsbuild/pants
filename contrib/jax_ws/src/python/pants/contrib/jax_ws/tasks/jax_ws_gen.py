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
from pants.java.distribution.distribution import DistributionLocator
from pants.task.simple_codegen_task import SimpleCodegenTask

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
    distribution = DistributionLocator.cached(jdk=True)
    # Note, using tools.jar will only work with Java 8 and lower.  The tools.jar does not exist
    # in JDK 9 and this will have to be revisted when Java 9 is released.
    # See http://openjdk.java.net/jeps/220 for more information
    classpath = distribution.find_libs(['tools.jar'])

    wsdl_directory = target.payload.sources.rel_path
    for source in target.payload.sources.source_paths:
      url = os.path.join(wsdl_directory, source)

      args = self._format_args_for_relative_path(target, target_workdir, url)

      result = self.runjava(
        classpath=classpath,
        main='com.sun.tools.internal.ws.WsImport',
        jvm_options=self.get_options().jvm_options,
        args=args,
        workunit_name='wsimport')
      if result != 0:
        raise TaskError('JAX-WS compiler exited non-zero ({0})'.format(result))

  def _format_args_for_relative_path(self, target, target_workdir, url):
    # Ported and trimmed down from:
    # https://java.net/projects/jax-ws-commons/sources/svn/content/trunk/
    # jaxws-maven-plugin/src/main/java/org/jvnet/jax_ws_commons/jaxws/WsImportMojo.java?rev=1191
    args = []
    if self.get_options().ws_verbose:
      args.append('-verbose')
    if self.get_options().ws_quiet:
      args.append('-quiet')
    args.append('-Xnocompile') # Always let pants do the compiling work.
    args.extend(['-keep', '-s', os.path.abspath(target_workdir)])
    args.extend(['-d', os.path.abspath(target_workdir)])
    if target.payload.xjc_args:
      args.extend(('-B{}'.format(a) if a.startswith('-') else a) for a in target.payload.xjc_args)
    args.append('-B-no-header') # Don't let xjc write out a timestamp, because it'll break caching.
    args.extend(target.payload.extra_args)
    args.append(url)
    if self.get_options().level == 'debug':
      args.append('-Xdebug')
    return args

  @property
  def _copy_target_attributes(self):
    """Propagate the provides attribute to the synthetic java_library() target for publishing."""
    return ['provides']
