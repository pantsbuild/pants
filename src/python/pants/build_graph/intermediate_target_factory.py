# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC
from hashlib import sha1

from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address


def hash_target(address, suffix):
    hasher = sha1()
    hasher.update(address.encode())
    hasher.update(suffix.encode())
    return hasher.hexdigest()


class IntermediateTargetFactoryBase(ABC):
    """Convenience factory which constructs an intermediate target with the appropriate
    attributes."""

    class ExpectedAddressError(TargetDefinitionException):
        """Thrown if an object that is not an address is used as the dependency spec."""

    def __init__(self, parse_context):
        self._parse_context = parse_context

    @property
    def extra_target_arguments(self):
        """Extra keyword arguments to pass to the target constructor."""
        return {}

    def _create_intermediate_target(self, address, suffix):
        """
        :param string address: A target address.
        :param string suffix: A string used as a suffix of the intermediate target name.
        :returns: The address of a synthetic intermediary target.
        """
        if not isinstance(address, str):
            raise self.ExpectedAddressError(
                f"Expected str address argument, got type {type(address)}"
            )
        address = Address.parse(address, self._parse_context.rel_path)
        # NB(gmalmquist): Ideally there should be a way to indicate that these targets are synthetic
        # and shouldn't show up in `./pants list` etc, because we really don't want people to write
        # handwritten dependencies on them. For now just give them names containing "-unstable-" as a
        # hint.
        hash_str = hash_target(str(address), suffix)
        name = "{name}-unstable-{suffix}-{index}".format(
            name=address.target_name, suffix=suffix.replace(" ", "."), index=hash_str,
        )

        self._parse_context.create_object_if_not_exists(
            "target", name=name, dependencies=[address.spec], **self.extra_target_arguments
        )

        return ":{}".format(name)
