from __future__ import print_function

import os
import time

from twitter.common.dirutil import touch
from twitter.common.python.fetcher import Fetcher, PyPIFetcher
from twitter.common.python.http import Crawler
from twitter.common.python.obtainer import Obtainer
from twitter.common.python.interpreter import PythonInterpreter
from twitter.common.python.platforms import Platform
from twitter.common.python.resolver import requirement_is_exact
from twitter.common.python.translator import (
    ChainedTranslator,
    EggTranslator,
    SourceTranslator)

from .python_setup import PythonSetup

from pkg_resources import (
    Environment,
    WorkingSet,
)


def get_platforms(platform_list):
  def translate(platform):
    return Platform.current() if platform == 'current' else platform
  return tuple(set(map(translate, platform_list)))


def fetchers_from_config(config):
  fetchers = []
  fetchers.extend(Fetcher([url]) for url in config.getlist('python-repos', 'repos', []))
  fetchers.extend(PyPIFetcher(url) for url in config.getlist('python-repos', 'indices', []))
  return fetchers


def crawler_from_config(config, conn_timeout=None):
  download_cache = PythonSetup(config).scratch_dir('download_cache', default_name='downloads')
  return Crawler(cache=download_cache, conn_timeout=conn_timeout)


class PantsEnvironment(Environment):

  # TODO(wickman) Use the twitter.common.python version once wheels are implemented there.
  def can_add(self, dist):
    return Platform.distribution_compatible(dist, python=self.python, platform=self.platform)


def resolve_multi(config,
                  requirements,
                  interpreter=None,
                  platforms=None,
                  conn_timeout=None,
                  ttl=3600):
  """Multi-platform dependency resolution for PEX files.

     Given a pants configuration and a set of requirements, return a list of distributions
     that must be included in order to satisfy them.  That may involve distributions for
     multiple platforms.

     :param config: Pants :class:`Config` object.
     :param requirements: A list of :class:`PythonRequirement` objects to resolve.
     :param interpreter: :class:`PythonInterpreter` for which requirements should be resolved.
                         If None specified, defaults to current interpreter.
     :param platforms: Optional list of platforms against requirements will be resolved. If
                         None specified, the defaults from `config` will be used.
     :param conn_timeout: Optional connection timeout for any remote fetching.
     :param ttl: Time in seconds before we consider re-resolving an open-ended requirement, e.g.
                 "flask>=0.2" if a matching distribution is available on disk.  Defaults
                 to 3600.
  """
  now = time.time()
  distributions = {}

  interpreter = interpreter or PythonInterpreter.get()
  if not isinstance(interpreter, PythonInterpreter):
    raise TypeError('Expected interpreter to be a PythonInterpreter, got %s' % type(interpreter))

  install_cache = PythonSetup(config).scratch_dir('install_cache', default_name='eggs')
  platforms = get_platforms(platforms or config.getlist('python-setup', 'platforms', ['current']))
  crawler = crawler_from_config(config, conn_timeout=conn_timeout)
  fetchers = fetchers_from_config(config)

  for platform in platforms:
    env = PantsEnvironment(search_path=[], platform=platform, python=interpreter.python)
    working_set = WorkingSet(entries=[])

    shared_options = dict(install_cache=install_cache, platform=platform)
    egg_translator = EggTranslator(python=interpreter.python, **shared_options)
    egg_obtainer = Obtainer(crawler, [Fetcher([install_cache])], egg_translator)

    def installer(req):
      # Attempt to obtain the egg from the local cache.  If it's an exact match, we can use it.
      # If it's not an exact match, then if it's been resolved sufficiently recently, we still
      # use it.
      dist = egg_obtainer.obtain(req)
      if dist and (requirement_is_exact(req) or now - os.path.getmtime(dist.location) < ttl):
        return dist

      # Failed, so follow through to "remote" resolution
      source_translator = SourceTranslator(
           interpreter=interpreter,
           use_2to3=getattr(req, 'use_2to3', False),
           **shared_options)
      translator = ChainedTranslator(egg_translator, source_translator)
      obtainer = Obtainer(
          crawler,
          [Fetcher([req.repository])] if getattr(req, 'repository', None) else fetchers,
          translator)
      dist = obtainer.obtain(req)
      if dist:
        try:
          touch(dist.location)
        except OSError:
          pass
      return dist

    distributions[platform] = working_set.resolve(requirements, env=env, installer=installer)

  return distributions
