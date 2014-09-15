# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.payload import EmptyPayload
from pants.base.target import Target


class Repository(Target):
  """An artifact repository, such as a maven repo."""

  def __init__(self, url=None, push_db_basedir=None, **kwargs):
    """
    :param string name: Name of the repository.
    :param string url: Optional URL of the repository.
    :param string push_db_basedir: Push history file base directory.
    """

    super(Repository, self).__init__(payload=EmptyPayload(), **kwargs)

    self.url = url
    self.push_db_basedir = push_db_basedir

  def push_db(self, target):
    return os.path.join(self.push_db_basedir, target.provides.org,
                        target.provides.name, 'publish.properties')

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
    return "%s -> %s (%s)" % (self.name, self.url, self.push_db_basedir)
