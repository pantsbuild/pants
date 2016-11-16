# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import subprocess

from pants.backend.codegen.subsystems.thrift_defaults import ThriftDefaults
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.binaries.thrift_binary import ThriftBinary
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from twitter.common.collections import OrderedSet

from pants.contrib.go.targets.go_thrift_library import GoThriftGenLibrary, GoThriftLibrary


class GoThriftGen(SimpleCodegenTask):

  @classmethod
  def register_options(cls, register):
    super(GoThriftGen, cls).register_options(register)

    register('--strict', default=True, fingerprint=True, type=bool,
             help='Run thrift compiler with strict warnings.')
    register('--gen-options', advanced=True, fingerprint=True,
            help='Use these apache thrift go gen options.')
    register('--thrift-import', advanced=True,
             help='Use this thrift-import gen option to thrift.')
    register('--thrift-import-target', advanced=True,
             help='Use this thrift import on symbolic defs.')

  @classmethod
  def subsystem_dependencies(cls):
    return (super(GoThriftGen, cls).subsystem_dependencies() +
            (ThriftDefaults, ThriftBinary.Factory.scoped(cls)))

  @memoized_property
  def _thrift_binary(self):
    thrift_binary = ThriftBinary.Factory.scoped_instance(self).create()
    return thrift_binary.path

  @memoized_property
  def _deps(self):
    thrift_import_target = self.get_options().thrift_import_target
    thrift_imports = self.context.resolve(thrift_import_target)
    return thrift_imports

  @memoized_property
  def _service_deps(self):
    service_deps = self.get_options().get('service_deps')
    return list(self.resolve_deps(service_deps)) if service_deps else self._deps

  SERVICE_PARSER = re.compile(r'^\s*service\s+(?:[^\s{]+)')
  NAMESPACE_PARSER = re.compile(r'^\s*namespace go\s+([^\s]+)', re.MULTILINE)

  def _declares_service(self, source):
    with open(source) as thrift:
      return any(line for line in thrift if self.SERVICE_PARSER.search(line))

  def _get_go_namespace(self, source):
    with open(source) as thrift:
      namespace = self.NAMESPACE_PARSER.search(thrift.read())
      if not namespace:
        raise TaskError('Thrift file {} must contain "namespace go "', source)
      return namespace.group(1)

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    for source in target.sources_relative_to_buildroot():
      if self._declares_service(os.path.join(get_buildroot(), source)):
        return self._service_deps
    return self._deps

  def synthetic_target_type(self, target):
    return GoThriftGenLibrary

  def is_gentarget(self, target):
    return isinstance(target, GoThriftLibrary)

  @memoized_property
  def _thrift_cmd(self):
    cmd = [self._thrift_binary]
    thrift_import = 'thrift_import={}'.format(self.get_options().thrift_import)
    gen_options = self.get_options().gen_options
    if gen_options:
      gen_options += ',' + thrift_import
    else:
      gen_options = thrift_import
    cmd.extend(('--gen', 'go:{}'.format(gen_options)))

    if self.get_options().strict:
      cmd.append('-strict')
    if self.get_options().level == 'debug':
      cmd.append('-verbose')
    return cmd

  def _generate_thrift(self, target, target_workdir):
    target_cmd = self._thrift_cmd[:]

    bases = OrderedSet(tgt.target_base for tgt in target.closure() if self.is_gentarget(tgt))
    for base in bases:
      target_cmd.extend(('-I', base))

    target_cmd.extend(('-o', target_workdir))

    all_sources = list(target.sources_relative_to_buildroot())
    if len(all_sources) != 1:
      raise TaskError('go_thrift_library only supports a single .thrift source file for {}.', target)

    source = all_sources[0]
    target_cmd.append(os.path.join(get_buildroot(), source))
    with self.context.new_workunit(name=source,
                                   labels=[WorkUnitLabel.TOOL],
                                   cmd=' '.join(target_cmd)) as workunit:
      result = subprocess.call(target_cmd,
                               stdout=workunit.output('stdout'),
                              stderr=workunit.output('stderr'))
      if result != 0:
        raise TaskError('{} ... exited non-zero ({})'.format(self._thrift_binary, result))

    gen_dir = os.path.join(target_workdir, 'gen-go')
    src_dir = os.path.join(target_workdir, 'src')
    safe_mkdir(src_dir)
    go_dir = os.path.join(target_workdir, 'src', 'go')
    os.rename(gen_dir, go_dir)

  @classmethod
  def product_types(cls):
    return ['go']

  def execute_codegen(self, target, target_workdir):
    self._generate_thrift(target, target_workdir)

  @property
  def _copy_target_attributes(self):
    """Override `_copy_target_attributes` to exclude `provides`."""
    return [a for a in super(GoThriftGen, self)._copy_target_attributes if a != 'provides']

  def synthetic_target_dir(self, target, target_workdir):
    all_sources = list(target.sources_relative_to_buildroot())
    source = all_sources[0]
    namespace = self._get_go_namespace(source)
    return os.path.join(target_workdir, 'src', 'go', namespace.replace(".", os.path.sep))
