# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os


class Repository:
  """An artifact repository, such as a maven repo.

  :API: public
  """

  def __init__(self, name=None, url=None, push_db_basedir=None, **kwargs):
    """
    :param string url: Optional URL of the repository.
    :param string push_db_basedir: Push history file base directory.
    """
    self.name = name
    self.url = url
    self.push_db_basedir = push_db_basedir

  def push_db(self, target):
    return os.path.join(self.push_db_basedir,
                        target.provides.org,
                        target.provides.name,
                        'publish.properties')

  def __eq__(self, other):
    return (
      isinstance(other, Repository) and
      (self.name, self.url, self.push_db_basedir) == (other.name, other.url, other.push_db_basedir)
    )

  def __hash__(self):
    return hash((self.name, self.url, self.push_db_basedir))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return f"{self.name} -> {self.url} ({self.push_db_basedir})"
