# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.target import Target


class GoRemoteLibrary(Target):
  """Represents a remote GO package."""
  # TODO(John Sirois): Consider a re-name and a semantics scan in the Go tasks.  A GoRemoteLibrary's
  # package can in fact be a GoBinary when materialized locally.  This suggests a name of
  # GoRemoteSource and an alias of 'go_remote'.  This also raises questions about support for things
  # like `./pants run 3rdaprty/go/github.com/docker/docker/docker` (yes - 3 dockers).  That _should_
  # execute the remote binary since that remote package is a 'main' package.
  # Tracked at: https://github.com/pantsbuild/pants/issues/2020

  @classmethod
  def remote_package_path(cls, remote_root, import_path):
    """Returns the remote package path portion of the given import path.

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

    :param string remote_root: The path to the remote; generally a scheme-less URL.
    :param string import_path: The full import path used to import the package in a `.go` source
                               file.
    :raises: `ValueError` if the import_path does not lay within the remote root.
    """
    package_path = os.path.relpath(import_path, remote_root)
    return cls._normalize_package_path(package_path)

  @classmethod
  def _normalize_package_path(cls, package_path):
    if package_path.startswith(os.pardir + os.sep):
      raise ValueError('Relative package paths are not allowed. Given: {!r}'.format(package_path))
    if os.path.isabs(package_path):
      raise ValueError('Absolute package paths are not allowed. Given: {!r}'.format(package_path))
    return '' if not package_path or package_path == os.curdir else package_path.lstrip('/')

  @classmethod
  def from_packages(cls, parse_context, rev='', packages=None, **kwargs):
    """
    :param list packages: The package import paths within the remote library; by default just the
                          root package will be available (equivalent to passing `packages=['']`).
    :param str rev: Identifies which version of the remote library to download. This could be a
                    commit SHA (git), node id (hg), etc.  If left unspecified the version will
                    default to the latest available.  It's highly recommended to not accept the
                    default and instead pin the rev explicitly for repeatable builds.
    """
    for pkg in packages:
      name = pkg or os.path.basename(parse_context.rel_path)
      parse_context.create_object(cls, name=name, pkg=pkg, rev=rev, **kwargs)

  # TODO(John Sirois): Hide this constructor so that user's cannot pass a name and thus 1:1:1 is
  # strictly enforced.  This will require means to expose a Target type to the BuildConfiguration
  # that macros can use without supplying an alias that BUILD authors can use.
  # Tracked at: https://github.com/pantsbuild/pants/issues/2019
  def __init__(self, pkg='', rev='', address=None, payload=None, **kwargs):
    """
    :param str pkg: The package import path within the remote library; by default the root package
                    path (equivalent to passing `pkg='.'` or `pkg=''`).
    :param str rev: Identifies which version of the remote library to download. This could be a
                    commit SHA (git), node id (hg), etc.  If left unspecified the version will
                    default to the latest available.  It's highly recommended to not accept the
                    default and instead pin the rev explicitly for repeatable builds.
    """
    if 'dependencies' in kwargs:
      raise TargetDefinitionException(address.spec,
                                      'A go_remote_library does not accept dependencies; instead, '
                                      'they are discovered and when they are on foreign remote '
                                      'libraries the versions are taken from other '
                                      'go_remote_library targets you\'ve defined in the same '
                                      'source root.')

    try:
      package_path = self._normalize_package_path(pkg)
    except ValueError as e:
      raise TargetDefinitionException(address.spec, str(e))

    payload = payload or Payload()
    payload.add_fields({
      'rev': PrimitiveField(rev or ''),  # Guard against/allow `None`.
      'pkg': PrimitiveField(package_path),
    })

    super(GoRemoteLibrary, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def pkg(self):
    return self.payload.pkg

  @property
  def rev(self):
    return self.payload.rev

  @property
  def import_path(self):
    rel_path = os.path.relpath(self.address.spec_path, self.target_base)
    return os.path.join(rel_path, self.pkg) if self.pkg else rel_path
