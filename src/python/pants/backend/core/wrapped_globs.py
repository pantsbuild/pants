# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.dirutil.fileset import Fileset

from pants.base.build_environment import get_buildroot


class FilesetRelPathWrapper(object):
  def __init__(self, rel_path):
    self.rel_path = rel_path

  def __call__(self, *args, **kwargs):
    root = os.path.join(get_buildroot(), self.rel_path)
    return self.wrapped_fn(root=root, *args, **kwargs)


class Globs(FilesetRelPathWrapper):
  wrapped_fn = Fileset.globs


class RGlobs(FilesetRelPathWrapper):
  wrapped_fn = Fileset.rglobs


class ZGlobs(FilesetRelPathWrapper):
  wrapped_fn = Fileset.zglobs
