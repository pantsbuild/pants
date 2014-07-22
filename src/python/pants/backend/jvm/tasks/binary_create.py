# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir


class BinaryCreate(JvmBinaryTask):
  """Creates a runnable monolithic binary deploy jar."""

  def __init__(self, context, workdir):
    super(BinaryCreate, self).__init__(context, workdir)
    self._outdir = context.config.getdefault('pants_distdir')

  def execute(self):
    for binary in self.context.targets(self.is_binary):
      self.create_binary(binary)

  def create_binary(self, binary):
    safe_mkdir(self._outdir)

    binary_jarname = '%s.jar' % binary.basename
    binary_jarpath = os.path.join(self._outdir, binary_jarname)
    self.context.log.info('creating %s' % os.path.relpath(binary_jarpath, get_buildroot()))

    with self.monolithic_jar(binary, binary_jarpath, with_external_deps=True) as jar:
      self.add_main_manifest_entry(jar, binary)
