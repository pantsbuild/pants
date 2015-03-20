# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.fetcher import Fetcher, PyPIFetcher
from pex.http import Context
from pkg_resources import Requirement


# TODO(benjy): These are basically proto-subsystems. There's some obvious commonality, but
# rather than factor that out now I'll retrofit these to use whatever general subsystem
# implementation we come up with in the near future.

class PythonSetup(object):
  """Configuration data for a python environment."""
  def __init__(self, config):
    self._config = config

  @property
  def interpreter_requirement(self):
    """Returns the repo-wide interpreter requirement."""
    return self._get_config('interpreter_requirement')

  @property
  def setuptools_version(self):
    return self._get_config('setuptools_version', default='5.4.1')

  @property
  def wheel_version(self):
    return self._get_config('wheel_version', default='0.23.0')

  @property
  def platforms(self):
    return self._get_config_list('platforms', default=['current'])

  @property
  def scratch_dir(self):
    return os.path.join(self._config.getdefault('pants_workdir'), 'python')

  def setuptools_requirement(self):
    return self._failsafe_parse('setuptools=={0}'.format(self.setuptools_version))

  def wheel_requirement(self):
    return self._failsafe_parse('wheel=={0}'.format(self.wheel_version))

  # This is a setuptools <1 and >1 compatible version of Requirement.parse.
  # For setuptools <1, if you did Requirement.parse('setuptools'), it would
  # return 'distribute' which of course is not desirable for us.  So they
  # added a replacement=False keyword arg.  Sadly, they removed this keyword
  # arg in setuptools >= 1 so we have to simply failover using TypeError as a
  # catch for 'Invalid Keyword Argument'.
  def _failsafe_parse(self, requirement):
    try:
      return Requirement.parse(requirement, replacement=False)
    except TypeError:
      return Requirement.parse(requirement)

  def _get_config(self, *args, **kwargs):
    return self._config.get('python-setup', *args, **kwargs)

  def _get_config_list(self, *args, **kwargs):
    return self._config.getlist('python-setup', *args, **kwargs)


class PythonRepos(object):
  """Configuration data for a python code repository."""
  def __init__(self, config):
    self._config = config

  @property
  def repos(self):
    return self._get_config_list('repos', [])

  @property
  def indexes(self):
    return self._get_config_list('indexes', [])

  def get_fetchers(self):
    fetchers = []
    fetchers.extend(Fetcher([url]) for url in self.repos)
    fetchers.extend(PyPIFetcher(url) for url in self.indexes)
    return fetchers

  def get_network_context(self):
    # TODO(wickman): Add retry, conn_timeout, threads, etc configuration here.
    return Context.get()

  def _get_config_list(self, *args, **kwargs):
    return self._config.getlist('python-repos', *args, **kwargs)
