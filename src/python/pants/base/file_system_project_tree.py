# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from glob import glob1

from pants.base.project_tree import ProjectTree
from pants.util.dirutil import fast_relpath, safe_walk


class FileSystemProjectTree(ProjectTree):
    def _join(self, relpath):
        if relpath.startswith(os.sep):
            raise ValueError('Absolute path "{}" not legal in {}.'.format(relpath, self))
        return os.path.join(self.build_root, relpath)

    def _glob1_raw(self, dir_relpath, glob):
        return glob1(self._join(dir_relpath), glob)

    def _isdir_raw(self, relpath):
        return os.path.isdir(self._join(relpath))

    def _isfile_raw(self, relpath):
        return os.path.isfile(self._join(relpath))

    def _exists_raw(self, relpath):
        return os.path.exists(self._join(relpath))

    def _content_raw(self, file_relpath):
        with open(self._join(file_relpath), "rb") as source:
            return source.read()

    def _relative_readlink_raw(self, relpath):
        return os.readlink(self._join(relpath))

    def _walk_raw(self, relpath, topdown=True):
        def onerror(error):
            raise OSError(
                getattr(error, "errno", None), "Failed to walk below {}".format(relpath), error
            )

        for root, dirs, files in safe_walk(self._join(relpath), topdown=topdown, onerror=onerror):
            yield fast_relpath(root, self.build_root), dirs, files

    def __eq__(self, other):
        return other and (type(other) == type(self)) and (self.build_root == other.build_root)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.build_root)

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, self.build_root)
