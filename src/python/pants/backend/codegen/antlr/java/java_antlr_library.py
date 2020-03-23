# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException
from pants.source.wrapped_globs import EagerFilesetWithSpec


class JavaAntlrLibrary(JvmTarget):
    """A Java library generated from Antlr grammar files."""

    def __init__(
        self,
        name=None,
        sources=None,
        provides=None,
        excludes=None,
        compiler="antlr3",
        package=None,
        **kwargs
    ):

        """
        :param provides: The ``artifact``
          to publish that represents this target outside the repo.
        :param compiler: The name of the compiler used to compile the ANTLR files.
            Currently only supports 'antlr3' and 'antlr4'
        :param package: (antlr4 only) A string which specifies the package to be used on the dependent
            sources.  If unset, the package will be based on the path to the sources. Note that if
            the sources are spread among different files, this must be set as the package cannot be
            inferred.
        """
        if compiler not in ("antlr3", "antlr4"):
            raise TargetDefinitionException(
                self, "Illegal value for 'compiler': {}.".format(compiler)
            )

        if isinstance(sources, EagerFilesetWithSpec):
            if sources.snapshot.is_empty:
                raise TargetDefinitionException(
                    self, "the sources parameter {} contains an empty snapshot.".format(sources)
                )
        elif not sources:
            raise TargetDefinitionException(self, "Missing required 'sources' parameter.")

        super().__init__(name=name, sources=sources, provides=provides, excludes=excludes, **kwargs)

        self.sources = sources
        self.compiler = compiler
        self.package = package
