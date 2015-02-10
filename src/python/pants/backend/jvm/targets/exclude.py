# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class Exclude(object):
  """Represents a dependency exclude pattern to filter transitive dependencies against."""

  def __init__(self, org, name=None):
    """
    :param string org: Organization of the artifact to filter,
      known as groupId in Maven parlance.
    :param string name: Name of the artifact to filter in the org, or filter
      everything if unspecified.
    """
    self.org = org
    self.name = name

  def __eq__(self, other):
    return all([other,
                type(other) == Exclude,
                self.org == other.org,
                self.name == other.name])

  def __lt__(self, other):
    return (self.org, self.name) < (other.org, other.name)

  def __gt__(self, other):
    return (other.org, other.name) < (self.org, self.name)

  def __hash__(self):
    return hash((self.org, self.name))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "Exclude(org='{0}', name='{1}')".format(self.org, self.name)
