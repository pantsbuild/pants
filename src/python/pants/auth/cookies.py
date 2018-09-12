# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from six.moves.http_cookiejar import LWPCookieJar

from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir_for


class BasicAuthException(Exception):
  pass


class Cookies(Subsystem):
  options_scope = 'cookies'

  @classmethod
  def register_options(cls, register):
    super(Cookies, cls).register_options(register)
    register('--path', advanced=True, default='~/.pants.cookies',
             help='Path to file that stores persistent cookies.')

  def update(self, cookies):
    """Add specified cookies to our cookie jar, and persists it.

    :param cookies: Any iterable that yields http.cookiejar.Cookie instances, such as a CookieJar.
    """
    cookie_jar = self.get_cookie_jar()
    for cookie in cookies:
      cookie_jar.set_cookie(cookie)
    cookie_jar.save()

  def get_cookie_jar(self):
    """Returns our cookie jar."""
    cookie_file = self._get_cookie_file()
    cookie_jar = LWPCookieJar(cookie_file)
    if os.path.exists(cookie_file):
      cookie_jar.load()
    else:
      safe_mkdir_for(cookie_file)
      # Save an empty cookie jar so we can change the file perms on it before writing data to it.
      cookie_jar.save()
      os.chmod(cookie_file, 0o600)
    return cookie_jar

  def _get_cookie_file(self):
    return os.path.realpath(os.path.expanduser(self.get_options().path))
