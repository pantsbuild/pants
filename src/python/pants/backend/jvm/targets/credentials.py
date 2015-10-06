# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.target import Target


class Credentials(Target):
  """Supplies credentials for a maven repository on demand.

  The ``publish.jar`` section of your ``pants.ini`` file can refer to one
  or more of these.
  """

  def __init__(self, username=None, password=None, **kwargs):
    """
    :param string name: The name of these credentials.
    :param username: Either a constant username value or else a callable that can fetch one.
    :type username: string or callable
    :param password: Either a constant password value or else a callable that can fetch one.
    :type password: string or callable
    """
    super(Credentials, self).__init__(**kwargs)
    self._username = username if callable(username) else lambda _: username
    self._password = password if callable(password) else lambda _: password

  def username(self, repository):
    """Returns the username in java system property argument form."""
    return self._username(repository)

  def password(self, repository):
    """Returns the password in java system property argument form."""
    return self._password(repository)
