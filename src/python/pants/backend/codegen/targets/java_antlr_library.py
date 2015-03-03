# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget


class JavaAntlrLibrary(JvmTarget):
  """Generates a stub Java library from Antlr grammar files."""

  def __init__(self,
               name=None,
               sources=None,
               provides=None,
               excludes=None,
               compiler='antlr3',
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

    if not sources:
      raise ValueError("Missing required 'sources' parameter.")
    self.sources = sources

    if compiler not in ('antlr3', 'antlr4'):
      raise ValueError("Illegal value for 'compiler': {}".format(compiler))
    self.compiler = compiler
    self.package = package
