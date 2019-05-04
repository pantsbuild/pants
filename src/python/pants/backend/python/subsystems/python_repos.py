# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pex.fetcher import Fetcher, PyPIFetcher
from pex.http import RequestsContext, requests

from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method

logger = logging.getLogger(__name__)


class PythonRepos(Subsystem):
  """A python code repository."""
  options_scope = 'python-repos'

  @classmethod
  def register_options(cls, register):
    super(PythonRepos, cls).register_options(register)
    register('--repos', advanced=True, type=list, default=[], fingerprint=True,
             help='URLs of code repositories.')
    register('--indexes', advanced=True, type=list, fingerprint=True,
             default=['https://pypi.org/simple/'], help='URLs of code repository indexes.')

  @property
  def repos(self):
    return self.get_options().repos

  @property
  def indexes(self):
    return self.get_options().indexes

  @memoized_method
  def get_fetchers(self):
    fetchers = []
    fetchers.extend(Fetcher([url]) for url in self.repos)
    fetchers.extend(PyPIFetcher(url) for url in self.indexes)
    return fetchers

  @memoized_method
  def get_network_context(self):
    # TODO(wickman): Add retry, conn_timeout, threads, etc configuration here.
    return RequestsContext()
