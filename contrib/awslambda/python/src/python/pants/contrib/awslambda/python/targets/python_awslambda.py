# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_binary import PythonBinary
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class PythonAWSLambda(Target):
    """A self-contained Python function suitable for uploading to AWS Lambda.

    :API: public
    """

    def __init__(self, binary=None, handler=None, **kwargs):
        """
        :param string binary: Target spec of the ``python_binary`` that contains the handler.
        :param string handler: Lambda handler entrypoint (module.dotted.name:handler_func).
        """
        payload = Payload()
        payload.add_fields({"binary": PrimitiveField(binary), "handler": PrimitiveField(handler)})
        super().__init__(payload=payload, **kwargs)

    @classmethod
    def alias(cls):
        return "python_awslambda"

    @classmethod
    def compute_dependency_address_specs(cls, kwargs=None, payload=None):
        for address_spec in super().compute_dependency_address_specs(kwargs, payload):
            yield address_spec
        target_representation = kwargs or payload.as_dict()
        binary = target_representation.get("binary")
        if binary:
            yield binary

    @property
    def binary(self):
        """Returns the binary that builds the pex for this lambda."""
        dependencies = self.dependencies
        if len(dependencies) != 1:
            raise TargetDefinitionException(
                self, f"An app must define exactly one binary dependency, have: {dependencies}"
            )
        binary = dependencies[0]
        if not isinstance(binary, PythonBinary):
            raise TargetDefinitionException(
                self, f"Expected binary dependency to be a python_binary target, found {binary}"
            )
        return binary

    @property
    def handler(self):
        """Return the handler function for the lambda."""
        return self.payload.handler
