# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.dirutil.fileset import Fileset

from pants.base.build_environment import get_buildroot


class FilesetRelPathWrapper(object):
  def __init__(self, parse_context):
    self.rel_path = parse_context.rel_path

  def __call__(self, *args, **kwargs):
    root = os.path.join(get_buildroot(), self.rel_path)

    for glob in args:
      if(self._is_glob_dir_outside_root(glob, root)):
        raise ValueError('Invalid glob %s, points outside BUILD file root dir %s' % (glob, root))

    return self.wrapped_fn(root=root, *args, **kwargs)

  def _is_glob_dir_outside_root(self, glob, root):
    # The assumption is that a correct glob starts with the root,
    # even after normalizing.
    glob_path = os.path.normpath(os.path.join(root, glob))

    # Check if the glob path has the correct root.
    return os.path.commonprefix([root, glob_path]) != root


class Globs(FilesetRelPathWrapper):
  """Returns Fileset containing matching files in same directory as this BUILD file.

  E.g., ``sources = globs('*java'),`` to get .java files in this directory.
  """
  wrapped_fn = Fileset.globs


class RGlobs(FilesetRelPathWrapper):
  """Recursive ``globs``, returns Fileset matching files in this directory and its "children.

  E.g., ``bundle().add(rglobs('config/*')),`` to bundle up all files in
  the config, config/foo, config/foo/bar directories.
  """
  wrapped_fn = Fileset.rglobs


class ZGlobs(FilesetRelPathWrapper):
  """Returns a Fileset that matches zsh-style globs, including ``**/`` for recursive globbing.

  Uses ``BUILD`` file's directory as the "working directory".
  """
  wrapped_fn = Fileset.zglobs
