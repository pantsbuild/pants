# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import collections
import os

from netrc import netrc as NetrcDb, NetrcParseError

from pants.tasks.task_error import TaskError


class Netrc(object):

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
        raise TaskError('A ~/.netrc file is required to authenticate')
      try:
        db = NetrcDb(db)
        for host, value in db.hosts.items():
          auth = db.authenticators(host)
          if auth:
            login, _, password = auth
            self._login[host] = login
            self._password[host] = password
        if len(self._login) == 0:
          raise TaskError('Found no usable authentication blocks in ~/.netrc')
      except NetrcParseError as e:
        raise TaskError('Problem parsing ~/.netrc: %s' % e)
