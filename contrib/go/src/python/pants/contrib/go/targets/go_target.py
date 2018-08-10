# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from abc import abstractproperty

from pants.build_graph.target import Target


class GoTarget(Target):
  @classmethod
  def package_path(cls, root, path):
    """Returns a normalized package path constructed from the given path and its root.

    A remote package path is the portion of the remote Go package's import path after the remote
    root path.

    For example, the remote import path 'https://github.com/bitly/go-simplejson' has
    a remote root of 'https://github.com/bitly/go-simplejson' and there is only 1 package
    in that remote root.  The package path in this case is '' or '.' and is normalized
    to ''.

    Some remote roots have no root package and others have both a root and sub-packages.  The
    remote root of 'github.com/docker/docker' is an example of the former.  One of the packages
    you might import from it is 'github.com/docker/docker/daemon/events' and that package has a
    normalized remote package path of 'daemon/events'.

    :param string root: The portion of `path` pointing to the go source code root.  This would be
                        `src` under a standard $GOPATH root.
    :param string path: The full path to the package.  This would be the full path to the package
                        directory relative to the $GOPATH.
    :raises: `ValueError` if the path does not lay within the root.
    """
    package_path = os.path.relpath(path, root)
    return cls.normalize_package_path(package_path)

  @classmethod
  def normalize_package_path(cls, package_path):
    """Returns a normalized version of the given package path.

    The root package might by denoted by '' or '.' and is normalized to ''.

    All other packages are of the form 'path' or 'path/subpath', etc.

    If the given path is either absolute or relative (includes the parent dir path signifier, '..'),
    then an error is raised since the path cannot be noramlized.

    :param string package_path: The Go package path to normalize.
    :raises: `ValueError` if the package path cannot be normalized.
    """
    if package_path.startswith(os.pardir + os.sep):
      raise ValueError('Relative package paths are not allowed. Given: {!r}'.format(package_path))
    if os.path.isabs(package_path):
      raise ValueError('Absolute package paths are not allowed. Given: {!r}'.format(package_path))
    return '' if not package_path or package_path == os.curdir else package_path.lstrip('/')

  @abstractproperty
  def import_path(self):
    """Returns the import path string that should be used to import this target's package.

    :returns: An import path that can be used to import this package in a `.go` file.
    :rtype: string
    """
