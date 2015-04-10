# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import io
import logging
import os
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.base.config import Config, SingleFileConfig
from pants.base.target import Target
from pants.goal.context import Context


def create_options(options):
  """Create a fake new-style options object for testing.

  Note that the returned object only provides access to the provided options values. There is
  no registration mechanism on this object. Code under test shouldn't care  about resolving
  cmd-line flags vs. config vs. env vars etc. etc.

  :param dict options: An optional dict of scope -> (dict of option name -> value).
  """
  class TestOptions(object):
    def for_scope(self, scope):
      class TestOptionValues(object):
        def __init__(self):
          self.__dict__ = options[scope]
        def __getitem__(self, key):
          return getattr(self, key)
      return TestOptionValues()

    def for_global_scope(self):
      return self.for_scope('')

    def passthru_args_for_scope(self, scope):
      return []

    def __getitem__(self, key):
      return self.for_scope(key)
  return TestOptions()


def create_empty_config():
  """Creates an empty ``Config``."""
  parser = Config.create_parser()
  with io.BytesIO(b'') as ini:
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

  def __init__(self, options, target_roots, build_graph=None, build_file_parser=None,
               address_mapper=None, console_outstream=None, workspace=None):
    # Some code still reads config directly. We have no tests left that actually care
    # about the values, but we still need something to read from so we don't crash.
    # TODO: Get rid of this once all direct config accesses are gone.
    empty_config = create_empty_config()
    super(TestContext, self).__init__(config=empty_config, options=options, run_tracker=None,
        target_roots=target_roots, build_graph=build_graph, build_file_parser=build_file_parser,
        address_mapper=address_mapper, console_outstream=console_outstream, workspace=workspace)
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


# TODO: Make Console and Workspace into subsystems, and simplify this signature.
def create_context(options=None, target_roots=None, build_graph=None,
                   build_file_parser=None, address_mapper=None,
                   console_outstream=None, workspace=None):
  """Creates a ``Context`` with no config values, options, or targets by default.

  :param options: A map of scope -> (map of key to value).

  Other params are as for ``Context``.
  """
  options = create_options(options or {})
  target_roots = maybe_list(target_roots, Target) if target_roots else []
  return TestContext(options=options, target_roots=target_roots, build_graph=build_graph,
                     build_file_parser=build_file_parser, address_mapper=address_mapper,
                     console_outstream=console_outstream, workspace=workspace)
