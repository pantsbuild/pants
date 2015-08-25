# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from glob import glob

from pants.base.payload import Payload

from pants.contrib.go.targets.go_target import GoTarget


class GoLocalSource(GoTarget):

  @classmethod
  def is_go_source(cls, path):
    return path.endswith('.go') and os.path.isfile(path)

  @classmethod
  def local_import_path(cls, source_root, address):
    """Returns the Go import path for the given address housed under the given source root.

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

    :param string source_root: The path of the source root the address is found within.
    :param address: The target address of a GoLocalSource target.
    :type: :class:`pants.base.address.Address`
    :raises: `ValueError` if the address does not reside within the source root.
    """
    return cls.package_path(source_root, address.spec_path)

  def __init__(self, address=None, payload=None, **kwargs):
    sources = glob(os.path.join(address.spec_path, '*.go'))
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path='',
                                           key_arg='sources'),
    })
    super(GoLocalSource, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def import_path(self):
    return self.local_import_path(self.target_base, self.address)
