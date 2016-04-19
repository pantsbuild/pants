# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
from abc import abstractmethod

from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.target import Target
from pants.util.memo import memoized_method
from pants.util.meta import AbstractClass
from pants.util.netrc import Netrc


class Credentials(Target, AbstractClass):
  """Credentials for a maven repository.

  The ``publish.jar`` section of your ``pants.ini`` file can refer to one
  or more of these.
  """

  @abstractmethod
  def username(self, repository):
    """Returns the username in java system property argument form."""

  @abstractmethod
  def password(self, repository):
    """Returns the password in java system property argument form."""


def _ignored_repository(value, repository):
  return value


class LiteralCredentials(Credentials):

  def __init__(self, username=None, password=None, **kwargs):
    """
    :param string name: The name of these credentials.
    :param username: A constant username value.
    :param password: A constant password value.
    """
    super(LiteralCredentials, self).__init__(**kwargs)

    if callable(username) or callable(password):
      raise TargetDefinitionException(self, 'The username and password arguments to credentials() '
                                            'cannot be callable. Use netrc_credentials() instead.')

    self._username = functools.partial(_ignored_repository, username)
    self._password = functools.partial(_ignored_repository, password)

  def username(self, repository):
    return self._username(repository)

  def password(self, repository):
    return self._password(repository)


class NetrcCredentials(Credentials):
  """A Credentials subclass that uses a Netrc file to compute credentials."""

  @memoized_method
  def _credentials(self, repository):
    netrc = Netrc()
    return (netrc.getusername(repository), netrc.getpassword(repository))

  def username(self, repository):
    """Returns the username in java system property argument form."""
    return self._credentials(repository)[0]

  def password(self, repository):
    """Returns the password in java system property argument form."""
    return self._credentials(repository)[1]
