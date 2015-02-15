# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tempfile
import time

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.targets.python_binary import PythonBinary
from pants.base.config import Config


class PythonBinaryBuilder(object):
  class NotABinaryTargetException(Exception):
    pass

  def __init__(self, context, target, run_tracker, interpreter=None):
    self.context = context
    self.target = target
    self.interpreter = interpreter or PythonInterpreter.get()
    if not isinstance(target, PythonBinary):
      raise PythonBinaryBuilder.NotABinaryTargetException(
          "Target %s is not a PythonBinary!" % target)

    config = Config.from_cache()
    self.distdir = config.getdefault('pants_distdir')
    distpath = tempfile.mktemp(dir=self.distdir, prefix=target.name)

    run_info = run_tracker.run_info
    build_properties = {}
    build_properties.update(run_info.add_basic_info(run_id=None, timestamp=time.time()))
    build_properties.update(run_info.add_scm_info())

    pexinfo = target.pexinfo.copy()
    pexinfo.build_properties = build_properties
    builder = PEXBuilder(distpath, pex_info=pexinfo, interpreter=self.interpreter)

    self.chroot = PythonChroot(
        context=self.context,
        targets=[target],
        builder=builder,
        platforms=target.platforms,
        interpreter=self.interpreter)

  def run(self):
    print('Building PythonBinary %s:' % self.target)
    env = self.chroot.dump()
    filename = os.path.join(self.distdir, '%s.pex' % self.target.name)
    env.build(filename)
    print('Wrote %s' % filename)
    return 0
