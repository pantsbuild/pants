# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class manual(object):
  """Annotate things that should appear in generated documents"""

  @staticmethod
  def builddict(tags=None):
    """Decorator to mark something that belongs in the BUILD Dictionary doc.

    Use it on a function to mention the function. Use it on a class to
    mention the class; use it on a class' method to mention that method
    within the class' doc. (Default behavior uses the constructor but
    ignores methods. You want to decorate methods that are kosher for
    BUILD files.)

    tags: E.g., tags=["python"] means This thingy should appear in the
          Python section"
    """
    tags = tags or []
    def builddictdecorator(funcorclass):
      funcorclass.builddictdict = {"tags": tags}
      return funcorclass
    return builddictdecorator


def get_builddict_info(funcorclass):
  """Return None if arg doesn't belong in BUILD dictionary, else something"""
  if hasattr(funcorclass, "builddictdict"):
    return getattr(funcorclass, "builddictdict")
  else:
    return None
