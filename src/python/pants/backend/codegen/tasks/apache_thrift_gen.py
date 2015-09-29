# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import shutil
import subprocess

from twitter.common.collections import OrderedSet

from pants.backend.codegen.subsystems.thrift_defaults import ThriftDefaults
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.binaries.thrift_binary import ThriftBinary
from pants.option.custom_types import list_option
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property


class ApacheThriftGen(SimpleCodegenTask):

  @classmethod
  def register_options(cls, register):
    super(ApacheThriftGen, cls).register_options(register)

    # NB: As of thrift 0.9.2 there is 1 warning that -strict promotes to an error - missing a
    # struct field id.  If an artifact was cached with strict off, we must re-gen with strict on
    # since this case may be present and need to generate a thrift compile error.
    register('--strict', default=True, fingerprint=True, action='store_true',
             help='Run thrift compiler with strict warnings.')

    register('--gen-options', advanced=True, fingerprint=True,
             help='Use these apache thrift java gen options.')
    register('--deps', advanced=True, type=list_option,
             help='A list of specs pointing to dependencies of thrift generated java code.')
    register('--service-deps', advanced=True, type=list_option,
             help='A list of specs pointing to dependencies of thrift generated java service '
                  'code.  If not supplied, then --deps will be used for service deps.')

  @classmethod
  def global_subsystems(cls):
    return super(ApacheThriftGen, cls).global_subsystems() + (ThriftDefaults,)

  @classmethod
  def task_subsystems(cls):
    return super(ApacheThriftGen, cls).task_subsystems() + (ThriftBinary.Factory,)

  @classmethod
  def subsystem_dependencies(cls):
    return (super(ApacheThriftGen, cls).subsystem_dependencies() +
            (ThriftDefaults, ThriftBinary.Factory.scoped(cls)))

  def __init__(self, *args, **kwargs):
    super(ApacheThriftGen, self).__init__(*args, **kwargs)
    self._thrift_defaults = ThriftDefaults.global_instance()

  @memoized_property
  def _thrift_binary(self):
    thrift_binary = ThriftBinary.Factory.scoped_instance(self).create()
    return thrift_binary.path

  def invalidate_for_files(self):
    # TODO: This will prevent artifact caching across platforms.
    # Find some cross-platform way to assert the thrift binary version.
    # NB: We have access to the version via the ThriftBinary instance's `version`, we just need
    # support for invalidation based on non-files.
    return [self._thrift_binary]

  @memoized_property
  def _deps(self):
    deps = self.get_options().deps
    return list(self.resolve_deps(deps)) if deps else []

  @memoized_property
  def _service_deps(self):
    service_deps = self.get_options().service_deps
    return list(self.resolve_deps(service_deps)) if service_deps else self._deps

  SERVICE_PARSER = re.compile(r'^\s*service\s+(?:[^\s{]+)')

  def _declares_service(self, source):
    with open(source) as thrift:
      return any(line for line in thrift if self.SERVICE_PARSER.search(line))

  def synthetic_target_extra_dependencies(self, target):
    for source in target.sources_relative_to_buildroot():
      if self._declares_service(os.path.join(get_buildroot(), source)):
        return self._service_deps
    return self._deps

  def synthetic_target_type(self, target):
    return JavaLibrary

  def is_gentarget(self, target):
    return (isinstance(target, JavaThriftLibrary) and
            'thrift' == self._thrift_defaults.compiler(target))

  @memoized_property
  def _thrift_cmd(self):
    cmd = [self._thrift_binary]

    gen_options = self.get_options().gen_options
    cmd.extend(('--gen', 'java:{}'.format(gen_options) if gen_options else 'java'))

    if self.get_options().strict:
      cmd.append('-strict')
    if self.get_options().level == 'debug':
      cmd.append('-verbose')
    return cmd

  def _generate_thrift(self, target):
    target_cmd = self._thrift_cmd[:]

    bases = OrderedSet(tgt.target_base for tgt in target.closure() if self.is_gentarget(tgt))
    for base in bases:
      target_cmd.extend(('-I', base))

    work_dir = self.codegen_workdir(target)
    safe_mkdir(work_dir, clean=True)
    target_cmd.extend(('-o', work_dir))

    for source in target.sources_relative_to_buildroot():
      cmd = target_cmd[:]
      cmd.append(os.path.join(get_buildroot(), source))
      with self.context.new_workunit(name=source,
                                     labels=[WorkUnitLabel.TOOL],
                                     cmd=' '.join(cmd)) as workunit:
        result = subprocess.call(cmd,
                                 stdout=workunit.output('stdout'),
                                 stderr=workunit.output('stderr'))
        if result != 0:
          raise TaskError('{} ... exited non-zero ({})'.format(self._thrift_binary, result))

    # The thrift compiler generates sources to a gen-[lang] subdir of the `-o` argument.  We
    # relocate the generated java sources to the root of the `work_dir` so that our base class
    # maps them properly for source jars and the like.
    gen_dir = os.path.join(work_dir, 'gen-java')
    for path in os.listdir(gen_dir):
      shutil.move(os.path.join(gen_dir, path), work_dir)
    os.rmdir(gen_dir)

  def execute_codegen(self, invalid_targets):
    for target in invalid_targets:
      self._generate_thrift(target)
