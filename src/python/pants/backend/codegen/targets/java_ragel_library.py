# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.build_manual import manual
from pants.base.config import Config
from pants.base.exceptions import TargetDefinitionException


class JavaRagelLibrary(JvmTarget):
  """Generates a stub Java library from a Ragel file."""

  def __init__(self,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """

    super(JavaRagelLibrary, self).__init__(**kwargs)

    self.add_labels('codegen')

  @property
  def is_ragel(self):
    return True
