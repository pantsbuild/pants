# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class manual(object):
  """Annotate things that should appear in generated documents"""

  @staticmethod
  def builddict(factory=False, suppress=False):
    """Decorator to indicate what belongs in the BUILD Dictionary doc.

    The BUILD Dictionary builder "decides" what goes in mostly by type. BUT:

    It omits most object methods. Decorate a method with
    @manual.builddict() to make it appear in the Dictionary.

    It includes most BUILD file aliases. Decorate a func/class
    with @manual.builddict(suppress=True) to omit that func/class.
    (Or call manual.builddict(suppress=True)(obj) on an object to omit that.)

    :param factory: Some registered a factory function. Instead of treating it
      as a function, we should find out what class it manufactures and use that.
    :param suppress: Directs dictionary builder to omit this thing.
    """
    def builddictdecorator(funcorclass):
      funcorclass.builddictdict = dict(factory=factory,
                                       suppress=suppress)
      return funcorclass
    return builddictdecorator


def get_builddict_info(funcorclass):
  """Return None if arg doesn't belong in BUILD dictionary, else something"""
  if hasattr(funcorclass, "builddictdict"):
    return getattr(funcorclass, "builddictdict")
  else:
    return None
