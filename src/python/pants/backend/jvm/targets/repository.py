# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.payload import EmptyPayload
from pants.base.target import Target


class Repository(Target):
  """An artifact repository, such as a maven repo."""

  def __init__(self, url=None, push_db=None, **kwargs):
    """
    :param string name: Name of the repository.
    :param string url: Optional URL of the repository.
    :param string push_db: Path of the push history file.
    """

    super(Repository, self).__init__(payload=EmptyPayload(), **kwargs)

    self.url = url
    self.push_db = push_db

  def __eq__(self, other):
    result = other and (
      type(other) == Repository) and (
      self.name == other.name)
    return result

  def __hash__(self):
    return hash(self.name)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s -> %s (%s)" % (self.name, self.url, self.push_db)
