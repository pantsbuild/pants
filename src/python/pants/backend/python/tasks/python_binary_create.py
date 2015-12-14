# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.pex_info import PexInfo

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.exceptions import TaskError


class PythonBinaryCreate(PythonTask):
  @staticmethod
  def is_binary(target):
    return isinstance(target, PythonBinary)

  def __init__(self, *args, **kwargs):
    super(PythonBinaryCreate, self).__init__(*args, **kwargs)
    self._distdir = self.get_options().pants_distdir

  def execute(self):
    binaries = self.context.targets(self.is_binary)

    # Check for duplicate binary names, since we write the pexes to <dist>/<name>.pex.
    names = {}
    for binary in binaries:
      name = binary.name
      if name in names:
        raise TaskError('Cannot build two binaries with the same name in a single invocation. '
                        '{} and {} both have the name {}.'.format(binary, names[name], name))
      names[name] = binary

    for binary in binaries:
      self.create_binary(binary)

  def create_binary(self, binary):
    interpreter = self.select_interpreter_for_targets(binary.closure())

    run_info_dict = self.context.run_tracker.run_info.get_as_dict()
    build_properties = PexInfo.make_build_properties()
    build_properties.update(run_info_dict)

    pexinfo = binary.pexinfo.copy()
    pexinfo.build_properties = build_properties

    with self.temporary_chroot(interpreter=interpreter, pex_info=pexinfo, targets=[binary],
                               platforms=binary.platforms) as chroot:
      pex_path = os.path.join(self._distdir, '{}.pex'.format(binary.name))
      chroot.package_pex(pex_path)
