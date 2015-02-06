# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.installer import Packager


class SdistBuilder(object):
  """A helper class to run setup.py projects."""

  class Error(Exception): pass
  class SetupError(Error): pass

  @classmethod
  def build(cls, setup_root, target, interpreter=None):
    packager = Packager(setup_root, interpreter=interpreter,
        install_dir=os.path.join(setup_root, 'dist'))
    try:
      return packager.sdist()
    except Packager.InstallFailure as e:
      raise cls.SetupError(str(e))
