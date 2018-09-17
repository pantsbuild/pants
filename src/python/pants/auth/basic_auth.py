# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import namedtuple

import requests

from pants.auth.cookies import Cookies
from pants.subsystem.subsystem import Subsystem


class BasicAuthException(Exception):
  pass


BasicAuthCreds = namedtuple('BasicAuthCreds', ['username', 'password'])


class BasicAuth(Subsystem):
  options_scope = 'basic_auth'

  @classmethod
  def register_options(cls, register):
    super(BasicAuth, cls).register_options(register)
    register('--providers', advanced=True, type=dict,
             help='Map from provider name to config dict. This dict contains the following items: '
                  '{url: <url of endpoint that accepts basic auth and sets a session cookie>}')

  @classmethod
  def subsystem_dependencies(cls):
    return super(BasicAuth, cls).subsystem_dependencies() + (Cookies,)

  def authenticate(self, provider, creds=None, cookies=None):
    """Authenticate against the specified provider.

    :param str provider: Authorize against this provider.
    :param pants.auth.basic_auth.BasicAuthCreds creds: The creds to use.
      If unspecified, assumes that creds are set in the netrc file.
    :param pants.auth.cookies.Cookies cookies: Store the auth cookies in this instance.
      If unspecified, uses the global instance.
    :raises pants.auth.basic_auth.BasicAuthException: If auth fails due to misconfiguration or
      rejection by the server.
    """
    cookies = cookies or Cookies.global_instance()

    if not provider:
      raise BasicAuthException('No basic auth provider specified.')

    provider_config = self.get_options().providers.get(provider)
    if not provider_config:
      raise BasicAuthException('No config found for provider {}.'.format(provider))

    url = provider_config.get('url')
    if not url:
      raise BasicAuthException('No url found in config for provider {}.'.format(provider_config))
    # TODO: Require url to be https, except when testing. See
    # https://github.com/pantsbuild/pants/issues/6496.

    if creds:
      auth = requests.auth.HTTPBasicAuth(creds.username, creds.password)
    else:
      auth = None  # requests will use the netrc creds.
    response = requests.get(url, auth=auth)
    if response.status_code != requests.codes.ok:
      raise BasicAuthException('Failed to auth against {}. Status code {}.'.format(
        response, response.status_code))
    cookies.update(response.cookies)
