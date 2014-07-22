# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class manual(object):
  """Annotate things that should appear in generated documents"""

  @staticmethod
  def builddict():
    """Decorator to mark a method that belongs in the BUILD Dictionary doc."""
    def builddictdecorator(funcorclass):
      funcorclass.builddictdict = {}
      return funcorclass
    return builddictdecorator


def get_builddict_info(funcorclass):
  """Return None if arg doesn't belong in BUILD dictionary, else something"""
  if hasattr(funcorclass, "builddictdict"):
    return getattr(funcorclass, "builddictdict")
  else:
    return None
