# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import os
from netrc import netrc as NetrcDb
from netrc import NetrcParseError


class Netrc(object):
  """Fetches username and password from ~/.netrc for logged in user."""

  class NetrcError(Exception):
    """Raised to indicate Netrc errors"""

    def __init__(self, *args, **kwargs):
      super(Netrc.NetrcError, self).__init__(*args, **kwargs)

  def __init__(self):
    self._login = collections.defaultdict(lambda: None)
    self._password = collections.defaultdict(lambda: None)

  def getusername(self, repository):
    self._ensure_loaded()
    return self._login[repository]

  def getpassword(self, repository):
    self._ensure_loaded()
    return self._password[repository]

  def _ensure_loaded(self):
    if not self._login and not self._password:
      db = os.path.expanduser('~/.netrc')
      if not os.path.exists(db):
        raise self.NetrcError('A ~/.netrc file is required to authenticate')
      try:
        db = NetrcDb(db)
        for host, value in db.hosts.items():
          auth = db.authenticators(host)
          if auth:
            login, _, password = auth
            self._login[host] = login
            self._password[host] = password
        if len(self._login) == 0:
          raise self.NetrcError('Found no usable authentication blocks in ~/.netrc')
      except NetrcParseError as e:
        raise self.NetrcError('Problem parsing ~/.netrc: {}'.format(e))
