# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from hashlib import sha1

from pants.base.payload_field import PayloadField
from pants.util.objects import datatype


class NativeArtifact(datatype(['lib_name']), PayloadField):
  """???"""

  # TODO: why do we need this to be a method and not e.g. a field?
  @classmethod
  def alias(cls):
    return 'native_artifact'

  def as_filename(self, platform):
    # TODO: check that the name conforms to some format (e.g. no dots?)
    return platform.resolve_platform_specific({
      'darwin': lambda: 'lib{}.dylib'.format(self.lib_name),
      'linux': lambda: 'lib{}.so'.format(self.lib_name),
    })

  def _compute_fingerprint(self):
    # FIXME: can we just use the __hash__ method here somehow?
    return sha1(self.lib_name).hexdigest()
