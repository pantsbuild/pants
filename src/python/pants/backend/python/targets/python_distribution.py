# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.util.collections import ensure_str_list


class PythonDistribution(PythonTarget):
    """A Python distribution target that accepts a user-defined setup.py."""

    default_sources_globs = "*.py"

    @classmethod
    def alias(cls):
        return "python_dist"

    def __init__(self, address=None, payload=None, sources=None, setup_requires=None, **kwargs):
        """
        :param address: The Address that maps to this Target in the BuildGraph.
        :type address: :class:`pants.build_graph.address.Address`
        :param payload: The configuration encapsulated by this target.  Also in charge of most
                        fingerprinting details.
        :type payload: :class:`pants.base.payload.Payload`
        :param sources: Files to "include". Paths are relative to the
          BUILD file's directory.
        :type sources: :class:`twitter.common.dirutil.Fileset` or list of strings. Must include
                       setup.py.
        :param list setup_requires: A list of python requirements to provide during the invocation of
                                    setup.py.
        """
        if "setup.py" not in sources:
            raise TargetDefinitionException(
                self,
                "A file named setup.py must be in the same "
                "directory as the BUILD file containing this target.",
            )

        payload = payload or Payload()
        payload.add_fields(
            {
                "setup_requires": PrimitiveField(
                    ensure_str_list(setup_requires or (), allow_single_str=True)
                )
            }
        )
        super().__init__(address=address, payload=payload, sources=sources, **kwargs)

    @property
    def has_native_sources(self):
        return self.has_sources(extension=tuple(self.native_source_extensions))

    @property
    def setup_requires(self):
        return self.payload.setup_requires
