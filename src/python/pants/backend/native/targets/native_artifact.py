# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from hashlib import sha1

from pants.base.payload_field import PayloadField


class NativeArtifact(PayloadField):
  """???"""

  # TODO: why do we need this to be a method and not e.g. a field?
  @classmethod
  def alias(cls):
    return 'native_artifact'

  def __init__(self, lib_name):
    super(NativeArtifact, self).__init__()
    self._lib_name = lib_name

  @property
  def lib_name(self):
    return self._lib_name

  def as_filename(self, platform):
    # TODO: check that the name conforms to some format (e.g. no dots?)
    return platform.resolve_platform_specific({
      'darwin': lambda: 'lib{}.dylib'.format(self.lib_name),
      'linux': lambda: 'lib{}.so'.format(self.lib_name),
    })

  def _compute_fingerprint(self):
    return sha1(self._lib_name).hexdigest()
