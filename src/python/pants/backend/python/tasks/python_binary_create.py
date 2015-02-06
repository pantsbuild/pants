# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.exceptions import TaskError


class PythonBinaryCreate(PythonTask):
  @staticmethod
  def is_binary(target):
    return isinstance(target, PythonBinary)

  def __init__(self, *args, **kwargs):
    super(PythonBinaryCreate, self).__init__(*args, **kwargs)
    self._distdir = self.context.config.getdefault('pants_distdir')

  def execute(self):
    binaries = self.context.targets(self.is_binary)

    # Check for duplicate binary names, since we write the pexes to <dist>/<name>.pex.
    names = {}
    for binary in binaries:
      name = binary.name
      if name in names:
        raise TaskError('Cannot build two binaries with the same name in a single invocation. '
                        '%s and %s both have the name %s.' % (binary, names[name], name))
      names[name] = binary

    for binary in binaries:
      self.create_binary(binary)

  def create_binary(self, binary):
    interpreter = self.select_interpreter_for_targets(binary.closure())

    run_info = self.context.run_tracker.run_info
    build_properties = {}
    build_properties.update(run_info.add_basic_info(run_id=None, timestamp=time.time()))
    build_properties.update(run_info.add_scm_info())

    pexinfo = binary.pexinfo.copy()
    pexinfo.build_properties = build_properties

    with self.temporary_pex_builder(pex_info=pexinfo, interpreter=interpreter) as builder:
      chroot = PythonChroot(
        context=self.context,
        targets=[binary],
        builder=builder,
        platforms=binary.platforms,
        interpreter=interpreter)

      pex_path = os.path.join(self._distdir, '%s.pex' % binary.name)
      chroot.dump()
      builder.build(pex_path)
