# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from hashlib import sha1

from future.utils import PY3

from pants.base.payload_field import PayloadField
from pants.util.objects import datatype, string_optional


class NativeArtifact(datatype([
    ('lib_name', string_optional),
    ('exe_name', string_optional),
]), PayloadField):
  """A BUILD file object declaring a target can be exported to other languages with a native ABI."""

  def __new__(cls, lib_name=None, exe_name=None):
    return super(NativeArtifact, cls).__new__(cls, lib_name=lib_name, exe_name=exe_name)

  # TODO: This should probably be made into an @classproperty (see PR #5901).
  @classmethod
  def alias(cls):
    return 'native_artifact'

  def as_shared_lib(self, platform):
    # TODO: check that the name conforms to some format in the constructor (e.g. no dots?).
    return platform.resolve_for_enum_variant({
      'darwin': 'lib{}.dylib'.format(self.lib_name),
      'linux': 'lib{}.so'.format(self.lib_name),
    })

  def _compute_fingerprint(self):
    # TODO: This fingerprint computation boilerplate is error-prone and could probably be
    # streamlined, for simple payload fields.
    hasher = sha1()
    hasher.update(self.lib_name.encode('utf-8') if self.lib_name else b"None")
    hasher.update(self.exe_name.encode('utf-8') if self.exe_name else b"None")
    return hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')
