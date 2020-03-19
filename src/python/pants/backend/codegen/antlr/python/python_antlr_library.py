# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_target import PythonTarget


class PythonAntlrLibrary(PythonTarget):
    """A Python library generated from Antlr grammar files."""

    # TODO: Deprecate antlr_version=, and replace it with a compiler= argument, that takes logical
    # names (antlr3, antlr4), like JavaAntlrLibrary.
    def __init__(self, module=None, compiler="antlr4", *args, **kwargs):
        """
    :param module: everything beneath module is relative to this module name, None if root namespace
    :param antlr_version:
    """
        if compiler not in ("antlr3", "antlr4"):
            raise TargetDefinitionException(
                self, "Illegal value for 'compiler': {}.".format(compiler)
            )
        super().__init__(*args, **kwargs)

        self.module = module
        self.compiler = compiler
