# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import FrozenInstanceError, dataclass
from hashlib import sha1
from typing import Any

from pants.base.payload_field import PayloadField
from pants.engine.platform import Platform
from pants.util.enums import match


# NB: We manually implement __hash__(), rather than using unsafe_hash=True, because PayloadField
# will mutate _fingerprint_memo and we must ensure that mutation does not affect the hash. For
# extra safety, we override __setattr__() to ensure that the hash can never be accidentally changed.
@dataclass
class NativeArtifact(PayloadField):
    """A BUILD file object declaring a target can be exported to other languages with a native
    ABI."""

    lib_name: str

    def __init__(self, lib_name: str) -> None:
        self.lib_name = lib_name
        self._is_frozen = True

    def __hash__(self) -> int:
        return hash(self.lib_name)

    def __setattr__(self, key: str, value: Any) -> None:
        if hasattr(self, "_is_frozen") and key == "lib_name":
            raise FrozenInstanceError(
                f"Attempting to modify the attribute {key} with value {value} on {self}."
            )
        super().__setattr__(key, value)

    # TODO: This should probably be made into an @classproperty (see PR #5901).
    @classmethod
    def alias(cls):
        return "native_artifact"

    def as_shared_lib(self, platform):
        # TODO: check that the name conforms to some format in the constructor (e.g. no dots?).
        return match(
            platform,
            {
                Platform.darwin: f"lib{self.lib_name}.dylib",
                Platform.linux: f"lib{self.lib_name}.so",
            },
        )

    def _compute_fingerprint(self):
        # TODO: This fingerprint computation boilerplate is error-prone and could probably be
        # streamlined, for simple payload fields.
        hasher = sha1(self.lib_name.encode())
        return hasher.hexdigest()
