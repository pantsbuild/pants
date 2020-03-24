# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_target import PythonTarget


class PythonAntlrLibrary(PythonTarget):
    """A Python library generated from Antlr grammar files."""

    def __init__(self, module=None, compiler="antlr4", *args, **kwargs):
        """
        :param module: everything beneath module is relative to this module name, None if root namespace
        :param compiler: The name of the compiler used to compile the ANTLR files.
            Currently only supports 'antlr3' and 'antlr4'
        """
        if compiler not in ("antlr3", "antlr4"):
            raise TargetDefinitionException(
                self, "Illegal value for 'compiler': {}.".format(compiler)
            )
        super().__init__(*args, **kwargs)

        self.module = module
        self.compiler = compiler
