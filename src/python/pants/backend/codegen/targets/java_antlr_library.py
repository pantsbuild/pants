# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary


class JavaAntlrLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from Antlr grammar files."""

  def __init__(self,
               name=None,
               sources=None,
               provides=None,
               excludes=None,
               compiler=None,
               package=None,
               **kwargs):

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

    super(JavaAntlrLibrary, self).__init__(name=name,
                                           sources=sources,
                                           provides=provides,
                                           excludes=excludes,
                                           **kwargs)
    self.add_labels('codegen')

    # TODO(John Sirois): fixup payload handling, including compiler and package as fields that
    # should invalidate on change ... package is conservative - a change in value may not actually
    # mean a change in the derived value.
    if not sources:
      raise ValueError("Missing required 'sources' parameter.")
    self.sources = sources

    self.compiler = compiler
    self.package = package
