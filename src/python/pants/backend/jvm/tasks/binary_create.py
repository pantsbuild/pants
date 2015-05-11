# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir


class BinaryCreate(JvmBinaryTask):
  """Creates a runnable monolithic binary deploy jar."""

  def __init__(self, *args, **kwargs):
    super(BinaryCreate, self).__init__(*args, **kwargs)
    self._outdir = self.get_options().pants_distdir

  @classmethod
  def product_types(cls):
    return ['jvm_binaries']

  def execute(self):
    for binary in self.context.targets(self.is_binary):
      self.create_binary(binary)

  def create_binary(self, binary):
    safe_mkdir(self._outdir)
    binary_jarname = '{}.jar'.format(binary.basename)
    binary_jarpath = os.path.join(self._outdir, binary_jarname)
    self.context.log.info('creating {}'.format(os.path.relpath(binary_jarpath, get_buildroot())))
    self.context.products.get('jvm_binaries').add(binary, self._outdir).append(binary_jarname)

    with self.monolithic_jar(binary, binary_jarpath, with_external_deps=True) as jar:
      self.add_main_manifest_entry(jar, binary)
