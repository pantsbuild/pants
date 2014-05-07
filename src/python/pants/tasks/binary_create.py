# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.dirutil import safe_mkdir

from pants.base.build_environment import get_buildroot
from pants.java.jar import Manifest
from pants.tasks.jvm_binary_task import JvmBinaryTask


class BinaryCreate(JvmBinaryTask):
  """Creates a runnable monolithic binary deploy jar."""

  def __init__(self, context, workdir):
    super(BinaryCreate, self).__init__(context, workdir)

    self._outdir = context.config.getdefault('pants_distdir')

    self.context.products.require('jars')
    self.require_jar_dependencies()

  def execute(self, targets):
    for binary in filter(self.is_binary, targets):
      self.create_binary(binary)

  def create_binary(self, binary):
    safe_mkdir(self._outdir)

    binary_jarname = '%s.jar' % binary.basename
    binary_jarpath = os.path.join(self._outdir, binary_jarname)
    self.context.log.info('creating %s' % os.path.relpath(binary_jarpath, get_buildroot()))

    with self.deployjar(binary, binary_jarpath) as jar:
      with self.context.new_workunit(name='add-manifest'):
        manifest = self.create_main_manifest(binary)
        jar.writestr(Manifest.PATH, manifest.contents())
