# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import warnings

from pants.build_graph.address import BuildFileAddress

logger = logging.getLogger(__name__)


# Note: Significant effort has been made to keep the types BuildFile, BuildGraph, Address, and
# Target separated appropriately.  The BuildFileParser is intended to have knowledge of just
# BuildFile and Address.
#
# Here are some guidelines to help maintain this abstraction:
#  - Use the terminology 'address' instead of 'target' in symbols and user messages
#  - Wrap exceptions from BuildFile with a subclass of BuildFileParserError
#     so that callers do not have to reference the BuildFile module
#
# Note: In general, 'spec' should not be a user visible term, it is usually appropriate to
# substitute 'address' instead.
class BuildFileParser:
    """Parses BUILD files for a given repo build configuration."""

    class BuildFileParserError(Exception):
        """Base class for all exceptions raised in BuildFileParser to make exception handling
        easier."""

        pass

    class BuildFileScanError(BuildFileParserError):
        """Raised if there was a problem when gathering all addresses in a BUILD file."""

        pass

    class AddressableConflictException(BuildFileParserError):
        """Raised if the same address is redefined in a BUILD file."""

        pass

    class SiblingConflictException(BuildFileParserError):
        """Raised if the same address is redefined in another BUILD file in the same directory."""

        pass

    class ParseError(BuildFileParserError):
        """An exception was encountered in the python parser."""

    class ExecuteError(BuildFileParserError):
        """An exception was encountered executing code in the BUILD file."""

    def __init__(self, build_configuration, root_dir):
        self._build_configuration = build_configuration
        self._root_dir = root_dir

    @property
    def root_dir(self):
        return self._root_dir

    def registered_aliases(self):
        """Returns a copy of the registered build file aliases this build file parser uses."""
        return self._build_configuration.registered_aliases()
