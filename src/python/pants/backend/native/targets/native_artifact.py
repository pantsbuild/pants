# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from hashlib import sha1

from pants.base.payload_field import PayloadField


# NB: We do not decorate this with @frozen_after_init because PayloadField must still mutate
# _fingerprint_memo. Even though PayloadField will change the value of _fingerprint_memo, the hash
# is still stable for NativeArtifact because unsafe_hash=True will only calculate it based on the
# `lib` attribute defined here. This works, so long as someone doesn't change the lib attribute.
@dataclass(unsafe_hash=True)
class NativeArtifact(PayloadField):
  """A BUILD file object declaring a target can be exported to other languages with a native ABI."""
  lib_name: str

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
    hasher = sha1(self.lib_name.encode())
    return hasher.hexdigest()
