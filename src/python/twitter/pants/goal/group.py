# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class Group(object):
  """Delineates a members of a group of targets that age sources for the same product types."""

  def __init__(self, name, predicate):
    """:param string name: A logical name for this group.
    :param predicate: A predicate that returns ``True`` if a given target is a member of this
                      group.
    """
    self.name = name
    self.predicate = predicate
    self.exclusives = None

  def __repr__(self):
    return "Group(%s,%s)" % (self.name, self.predicate.__name__)
