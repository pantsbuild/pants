# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from itertools import chain

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir, safe_mkdir_for

from pants.contrib.go.targets.go_target import GoTarget
from pants.contrib.go.tasks.go_task import GoTask


class GoWorkspaceTask(GoTask):
  """Sets up a standard Go workspace and links Go source code to the workspace.

  Enables the use of Go tools which require a $GOPATH and correctly organized
  "src/", "pkg/", and "bin/" directories (e.g. `go install` or `go test`).

  Intended as a super class for tasks which require and maintain a Go workspace.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoWorkspaceTask, cls).prepare(options, round_manager)
    round_manager.require_data('go_remote_lib_src')

  def get_gopath(self, target):
    """Returns the $GOPATH for the given target."""
    return os.path.join(self.workdir, target.id)

  def ensure_workspace(self, target):
    """Ensures that an up-to-date Go workspace exists for the given target.

    Creates any necessary symlinks to source files based on the target and its transitive
    dependencies, and removes any symlinks which do not correspond to any needed dep.
    """
    gopath = self.get_gopath(target)
    for d in ('bin', 'pkg', 'src'):
      safe_mkdir(os.path.join(gopath, d))
    required_links = set()
    for dep in target.closure():
      if not isinstance(dep, GoTarget):
        continue
      if self.is_remote_lib(dep):
        self._symlink_remote_lib(gopath, dep, required_links)
      else:
        self._symlink_local_src(gopath, dep, required_links)
    self.remove_unused_links(os.path.join(gopath, 'src'), required_links)

  @staticmethod
  def remove_unused_links(dirpath, required_links):
    """Recursively remove any links in dirpath which are not contained in required_links.

    :param str dirpath: Absolute path of directory to search.
    :param container required_links: Container of "in use" links which should not be removed,
                                     where each link is an absolute path.
    """
    for root, dirs, files in os.walk(dirpath):
      for p in chain(dirs, files):
        p = os.path.join(root, p)
        if os.path.islink(p) and p not in required_links:
          os.unlink(p)

  def _symlink_local_src(self, gopath, go_local_src, required_links):
    """Creates symlinks from the given gopath to the source files of the given local package.

    Also duplicates directory structure leading to source files of package within
    gopath, in order to provide isolation to the package.

    Adds the symlinks to the source files to required_links.
    """
    source_list = [os.path.join(get_buildroot(), src)
                   for src in go_local_src.sources_relative_to_buildroot()]
    rel_list = go_local_src.sources_relative_to_target_base()
    source_iter = zip(source_list, rel_list)
    return self._symlink_lib(gopath, go_local_src, source_iter, required_links)

  def _symlink_remote_lib(self, gopath, go_remote_lib, required_links):
    """Creates symlinks from the given gopath to the source files of the given remote lib.

    Also duplicates directory structure leading to source files of package within
    gopath, in order to provide isolation to the package.

    Adds the symlinks to the source files to required_links.
    """
    def source_iter():
      remote_lib_source_dir = self.context.products.get_data('go_remote_lib_src')[go_remote_lib]
      for path in os.listdir(remote_lib_source_dir):
        remote_src = os.path.join(remote_lib_source_dir, path)
        # We grab any file since a go package might have .go, .c, .cc, etc files - all needed for
        # installation.
        if os.path.isfile(remote_src):
          yield (remote_src, os.path.basename(path))
    return self._symlink_lib(gopath, go_remote_lib, source_iter(), required_links)

  def _symlink_lib(self, gopath, lib, source_iter, required_links):
    src_dir = os.path.join(gopath, 'src', lib.import_path)
    safe_mkdir(src_dir)
    for path, dest in source_iter:
      src_link = os.path.join(src_dir, dest)
      safe_mkdir_for(src_link)
      if not os.path.islink(src_link):
        os.symlink(path, src_link)
      required_links.add(src_link)
