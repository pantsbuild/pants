# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary


@manual.builddict(tags=["jvm"])
class JavaAntlrLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from Antlr grammar files."""

  def __init__(self,
               name,
               sources,
               provides=None,
               excludes=None,
               compiler='antlr3',
               package=None,
               **kwargs):

    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param Artifact provides:
      The :class:`pants.targets.artifact.Artifact`
      to publish that represents this target outside the repo.
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param compiler: The name of the compiler used to compile the ANTLR files.
        Currently only supports 'antlr3' and 'antlr4'
    :param package: A string which specifies the package to be used on the dependent sources.
        If unset, the package will be based on the path to the sources. Note that if the sources
        Are spread among different files, this must be set as the package cannot be inferred.
    """

    super(JavaAntlrLibrary, self).__init__(self,
                                           name=name,
                                           sources=sources,
                                           provides=provides,
                                           excludes=excludes,
                                           **kwargs)
    self.add_labels('codegen')

    if compiler not in ('antlr3', 'antlr4'):
        raise ValueError("Illegal value for 'compiler': {}".format(compiler))
    self.compiler = compiler
    self.package = package
