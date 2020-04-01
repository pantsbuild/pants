# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.fs import archive as archive_lib

from pants.contrib.node.targets.node_package import NodePackage


class NodeBundle(NodePackage):
    """A bundle of node modules."""

    def __init__(self, node_module=None, archive="tgz", address=None, payload=None, **kwargs):
        """
        :param dependencies: a list of node_modules

        :param archive: a string, select from tar, tgz, tbz2, default to tgz
        """
        if archive not in archive_lib.TYPE_NAMES_PRESERVE_SYMLINKS:
            raise TargetDefinitionException(
                self,
                "{} is not a valid archive type. Allowed archive types are {}".format(
                    archive, ", ".join(sorted(list(archive_lib.TYPE_NAMES_PRESERVE_SYMLINKS)))
                ),
            )

        if not node_module:
            raise TargetDefinitionException(self, "node_module can not be empty.")

        payload = payload or Payload()
        payload.add_fields(
            {"archive": PrimitiveField(archive), "node_module": PrimitiveField(node_module)}
        )
        super().__init__(address=address, payload=payload, **kwargs)

    @classmethod
    def compute_dependency_address_specs(cls, kwargs=None, payload=None):
        for address_spec in super().compute_dependency_address_specs(kwargs, payload):
            yield address_spec

        target_representation = kwargs or payload.as_dict()
        address_spec = target_representation.get("node_module")
        if address_spec:
            yield address_spec

    @property
    def node_module(self):
        if len(self.dependencies) != 1:
            raise TargetDefinitionException(
                self,
                "A node_bundle must define exactly one node_module dependency, have {}".format(
                    self.dependencies
                ),
            )
        else:
            return self.dependencies[0]
