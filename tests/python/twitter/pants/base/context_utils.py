# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import io

from twitter.common.collections import maybe_list
from twitter.common.dirutil import safe_mkdtemp
from twitter.common.lang import Compatibility

from twitter.pants.base.config import Config
from twitter.pants.base.target import Target
from twitter.pants.goal import Context, RunTracker
from twitter.pants.reporting.report import Report


def create_options(options_hash=None):
  """Creates an options object populated with no options at all by default.

  :param dict options_hash: An optional dict of option values.
  """
  opts = options_hash or {}
  if not isinstance(opts, dict):
    raise ValueError('The given options_hash must be a dict, got: %s' % options_hash)

  class Options(object):
    def __init__(self):
      self.__dict__ = opts
  return Options()


def create_config(sample_ini='', defaults=None):
  """Creates a ``Config`` from the ``sample_ini`` file contents.

  :param string sample_ini: The contents of the ini file containing the config values.
  :param dict defaults: An optional dict of global default ini values to seed.
  """
  if not isinstance(sample_ini, Compatibility.string):
    raise ValueError('The sample_ini supplied must be a string, given: %s' % sample_ini)

  parser = Config.create_parser(defaults)
  with io.BytesIO(sample_ini) as ini:
    parser.readfp(ini)
  return Config(parser)


def create_context(config='', options=None, target_roots=None, **kwargs):
  """Creates a ``Context`` with no config values, options, or targets by default.

  :param config: Either a ``Context`` object or else a string representing the contents of the
    pants.ini to parse the config from.
  :param options: An optional dict of of option values.
  :param target_roots: An optional list of target roots to seed the context target graph from.
  :param ``**kwargs``: Any additional keyword arguments to pass through to the Context constructor.
  """
  config = config if isinstance(config, Config) else create_config(config)

  # TODO(John Sirois): Rework uses around a context manager for cleanup of the info_dir in a more
  # disciplined manner
  info_dir = safe_mkdtemp()
  run_tracker = RunTracker(info_dir)
  report = Report()
  run_tracker.start(report)

  target_roots = maybe_list(target_roots, Target) if target_roots else []
  return Context(config, create_options(options or {}), run_tracker, target_roots, **kwargs)
