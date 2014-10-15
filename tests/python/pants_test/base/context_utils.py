# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import io
import sys
from twitter.common.collections import maybe_list
from twitter.common.lang import Compatibility

from pants.base.config import Config
from pants.base.target import Target
from pants.goal.context import Context
from pants.goal.run_tracker import RunTracker
from pants.reporting.plaintext_reporter import PlainTextReporter
from pants.reporting.report import Report
from pants.util.dirutil import safe_mkdtemp


def create_new_options(new_options=None):
  """Create a fake new-style options object for testing.

  Note that the returned object only provides access to the provided options values. There is
  no registration mechanism on this object. Code under test shouldn't care  about resolving
  cmd-line flags vs. config vs. env vars etc. etc.

  :param dict new_options: An optional dict of scope -> (dict of option name -> value).
  """
  class TestOptions(object):
    def for_scope(self, scope):
      class TestOptionValues(object):
        def __init__(self):
          self.__dict__ = new_options[scope]
      return TestOptionValues()

    def for_global_scope(self):
      return self.for_scope('')

  return TestOptions()

def create_options(options_hash=None):
  """Creates an old-style options object populated with no options at all by default.

  :param dict options_hash: An optional dict of option values.
  """
  opts = options_hash or {}
  if not isinstance(opts, dict):
    raise ValueError('The given options_hash must be a dict, got: %s' % options_hash)

  class OldOptions(object):
    def __init__(self):
      self.__dict__ = opts
  return OldOptions()


def create_config(sample_ini='', defaults=None):
  """Creates a ``Config`` from the ``sample_ini`` file contents.

  :param string sample_ini: The contents of the ini file containing the config values.
  :param dict defaults: An optional dict of global default ini values to seed.
  """
  if not isinstance(sample_ini, Compatibility.string):
    raise ValueError('The sample_ini supplied must be a string, given: %s' % sample_ini)

  parser = Config.create_parser(defaults)
  with io.BytesIO(sample_ini.encode('utf-8')) as ini:
    parser.readfp(ini)
  return Config(parser)


def create_run_tracker(info_dir=None):
  """Creates a ``RunTracker`` and starts it.

  :param string info_dir: An optional director for the run tracker to store state; defaults to a
    new temp dir that will be be cleaned up on interpreter exit.
  """
  # TODO(John Sirois): Rework uses around a context manager for cleanup of the info_dir in a more
  # disciplined manner
  info_dir = info_dir or safe_mkdtemp()
  run_tracker = RunTracker(info_dir)
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


def create_context(config='', old_options=None, new_options=None, target_roots=None, **kwargs):
  """Creates a ``Context`` with no config values, options, or targets by default.

  :param config: Either a ``Context`` object or else a string representing the contents of the
    pants.ini to parse the config from.
  :param old_options: An optional dict of old-style option values.
  :param new_options: An optional dict of scope -> (dict of name -> new-style option values).
  :param target_roots: An optional list of target roots to seed the context target graph from.
  :param ``**kwargs``: Any additional keyword arguments to pass through to the Context constructor.
  """
  config = config if isinstance(config, Config) else create_config(config)
  run_tracker = create_run_tracker()
  target_roots = maybe_list(target_roots, Target) if target_roots else []
  return Context(config, create_options(old_options or {}), create_new_options(new_options),
                 run_tracker, target_roots, **kwargs)
