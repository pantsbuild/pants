# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import io
import logging
import os
from contextlib import contextmanager

from six import string_types
from twitter.common.collections import maybe_list

from pants.base.config import Config, SingleFileConfig
from pants.base.target import Target
from pants.goal.context import Context


def create_option_values(option_values):
  """Create a fake OptionValues object for testing.

  :param dict option_values: A dict of option name -> value.
  """
  class TestOptionValues(object):
    def __init__(self):
      self.__dict__ = option_values
    def __getitem__(self, key):
      return getattr(self, key)
  return TestOptionValues()


def create_options(options):
  """Create a fake Options object for testing.

  Note that the returned object only provides access to the provided options values. There is
  no registration mechanism on this object. Code under test shouldn't care about resolving
  cmd-line flags vs. config vs. env vars etc. etc.

  :param dict options: A dict of scope -> (dict of option name -> value).
  """
  class TestOptions(object):
    def for_scope(self, scope):
      return create_option_values(options[scope])

    def for_global_scope(self):
      return self.for_scope('')

    def passthru_args_for_scope(self, scope):
      return []

    def __getitem__(self, key):
      return self.for_scope(key)
  return TestOptions()


def create_config(sample_ini=''):
  """Creates a ``Config`` from the ``sample_ini`` file contents.

  :param string sample_ini: The contents of the ini file containing the config values.
  """
  if not isinstance(sample_ini, string_types):
    raise ValueError('The sample_ini supplied must be a string, given: %s' % sample_ini)

  parser = Config.create_parser()
  with io.BytesIO(sample_ini.encode('utf-8')) as ini:
    parser.readfp(ini)
  return SingleFileConfig('dummy/path', parser)


class TestContext(Context):
  """A Context to use during unittesting.

  Stubs out various dependencies that we don't want to introduce in unit tests.

  TODO: Instead of extending the runtime Context class, create a Context interface and have
  TestContext and a runtime Context implementation extend that. This will also allow us to
  isolate the parts of the interface that a Task is allowed to use vs. the parts that the
  task-running machinery is allowed to use.
  """
  class DummyWorkunit(object):
    """A workunit stand-in that sends all output to /dev/null.

    These outputs are typically only used by subprocesses spawned by code under test, not
    the code under test itself, and would otherwise go into some reporting black hole anyway.

    Provides no other tracking/labeling/reporting functionality. Does not require "opening"
    or "closing".
    """
    def __init__(self, devnull):
      self._devnull = devnull

    def output(self, name):
      return self._devnull

    def set_outcome(self, outcome):
      pass

  def __init__(self, *args, **kwargs):
    super(TestContext, self).__init__(*args, **kwargs)
    try:
      from subprocess import DEVNULL # Python 3.
    except ImportError:
      DEVNULL = open(os.devnull, 'wb')
    self._devnull = DEVNULL

  @contextmanager
  def new_workunit(self, name, labels=None, cmd=''):
    yield TestContext.DummyWorkunit(self._devnull)

  @property
  def log(self):
    return logging.getLogger('test')


def create_context(config='', options=None, target_roots=None, **kwargs):
  """Creates a ``Context`` with no config values, options, or targets by default.

  :param config: Either a ``Context`` object or else a string representing the contents of the
    pants.ini to parse the config from.
  :param options: An optional dict of scope -> (dict of name -> new-style option values).
  :param target_roots: An optional list of target roots to seed the context target graph from.
  :param ``**kwargs``: Any additional keyword arguments to pass through to the Context constructor.
  """
  config = config if isinstance(config, Config) else create_config(config)
  # TODO: Get rid of this temporary hack after we plumb options through everywhere and can get
  # rid of the config cache.
  Config.cache(config)

  target_roots = maybe_list(target_roots, Target) if target_roots else []
  return TestContext(config=config, options=create_options(options or {}),
                     run_tracker=None, target_roots=target_roots, **kwargs)
