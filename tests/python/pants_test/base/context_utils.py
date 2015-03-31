# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import io
import sys

from six import string_types
from twitter.common.collections import maybe_list

from pants.base.config import Config, SingleFileConfig
from pants.base.target import Target
from pants.goal.context import Context
from pants.goal.run_tracker import RunTracker
from pants.reporting.plaintext_reporter import PlainTextReporter
from pants.reporting.report import Report
from pants.util.dirutil import safe_mkdtemp


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


def create_run_tracker():
  """Creates a ``RunTracker`` and starts it."""
  # TODO(John Sirois): Rework uses around a context manager for cleanup of the info_dir in a more
  # disciplined manner.
  # The RunTracker writes its info into <pants_workdir>/run-tracker.  But it's not important that
  # it be under the pants_workdir the rest of the code sees, so here we just give it a tmpdir
  # for this (but no other) purpose.
  # TODO(benjy): Some more regular way to set up a temporary buildroot and pants_workdir for tests.
  # TODO(benjy): Find a way to get rid of this? Tests shouldn't require a run tracker or reporter.
  workdir = safe_mkdtemp()
  run_tracker = RunTracker('run-tracker', create_option_values({
    'pants_workdir': workdir,
  }))
  report = Report()
  settings = PlainTextReporter.Settings(outfile=sys.stdout,
                                        log_level=Report.INFO,
                                        color=False,
                                        indent=True,
                                        timing=False,
                                        cache_stats=False)
  report.add_reporter('test_debug', PlainTextReporter(run_tracker, settings))
  run_tracker.start(report)
  return run_tracker


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

  run_tracker = create_run_tracker()
  target_roots = maybe_list(target_roots, Target) if target_roots else []
  return Context(config, create_options(options or {}),
                 run_tracker, target_roots, **kwargs)
