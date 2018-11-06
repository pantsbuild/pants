# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import getpass
from builtins import input

from colors import cyan, green, red

from pants.auth.basic_auth import BasicAuth, BasicAuthCreds, Challenged
from pants.base.exceptions import TaskError
from pants.task.console_task import ConsoleTask


class Login(ConsoleTask):
  """Task to auth against some identity provider.

  :API: public
  """

  @classmethod
  def subsystem_dependencies(cls):
    return super(Login, cls).subsystem_dependencies() + (BasicAuth,)

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def register_options(cls, register):
    super(Login, cls).register_options(register)
    register('--to', fingerprint=True,
             help='Log in to this provider.  Can also be specified as a passthru arg.')

  def console_output(self, targets):
    if targets:
      raise TaskError('The login task does not take any target arguments.')

    # TODO: When we have other auth methods (e.g., OAuth2), select one by provider name.
    requested_providers = list(filter(None, [self.get_options().to] + self.get_passthru_args()))
    if len(requested_providers) != 1:
      raise TaskError('Must specify exactly one provider.')
    provider = requested_providers[0]
    try:
      BasicAuth.global_instance().authenticate(provider)
      return ['', 'Logged in successfully using .netrc credentials.']
    except Challenged as e:
      creds = self._ask_for_creds(provider, e.url, e.realm)
      BasicAuth.global_instance().authenticate(provider, creds=creds)
    return ['', 'Logged in successfully.']

  @staticmethod
  def _ask_for_creds(provider, url, realm):
    print(green('\nEnter credentials for:\n'))
    print('{} {}'.format(green('Provider:'), cyan(provider)))
    print('{} {}'.format(green('Realm:   '), cyan(realm)))
    print('{} {}'.format(green('URL:     '), cyan(url)))
    print(red('\nONLY ENTER YOUR CREDENTIALS IF YOU TRUST THIS SITE!\n'))
    username = input(green('Username: '))
    password = getpass.getpass(green('Password: '))
    return BasicAuthCreds(username, password)
