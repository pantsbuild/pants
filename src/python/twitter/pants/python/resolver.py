from __future__ import print_function

from twitter.common.collections import OrderedSet
from twitter.common.python.fetcher import Fetcher, PyPIFetcher
from twitter.common.python.http import Crawler
from twitter.common.python.obtainer import Obtainer
from twitter.common.python.platforms import Platform
from twitter.common.python.resolver import ResolverBase
from twitter.common.python.translator import (
    ChainedTranslator,
    EggTranslator,
    SourceTranslator)

from twitter.pants.targets import (
    PythonBinary,
    PythonRequirement)


def get_platforms(platform_list):
  def translate(platform):
    return Platform.current() if platform == 'current' else platform
  return tuple(map(translate, platform_list))


class MultiResolver(ResolverBase):
  """A multi-platform PythonRequirement resolver for Pants."""

  @classmethod
  def fetchers(cls, config, target=None):
    fetchers = []
    fetchers.extend(Fetcher([url]) for url in config.getlist('python-repos', 'repos', []))
    fetchers.extend(PyPIFetcher(url) for url in config.getlist('python-repos', 'indices', []))
    if target and isinstance(target, PythonBinary):
      fetchers.extend(Fetcher([url]) for url in target.repositories)
      fetchers.extend(PyPIFetcher(url) for url in target.indices)
    return fetchers

  @classmethod
  def crawler(cls, config, conn_timeout=None):
    return Crawler(cache=config.get('python-setup', 'download_cache'),
                   conn_timeout=conn_timeout)

  def __init__(self, config, target, conn_timeout=None):
    platforms = config.getlist('python-setup', 'platforms', ['current'])
    if isinstance(target, PythonBinary) and target.platforms:
      platforms = target.platforms
    self._install_cache = config.get('python-setup', 'install_cache')
    self._crawler = self.crawler(config, conn_timeout=conn_timeout)
    self._fetchers = self.fetchers(config, target)
    self._platforms = get_platforms(platforms)
    super(MultiResolver, self).__init__(cache=self._install_cache)

  def make_installer(self, reqs, interpreter, platform):
    assert len(reqs) == 1 and isinstance(reqs[0], PythonRequirement), 'Got requirement list: %s' % (
      repr(reqs))
    req = reqs[0]
    fetchers = [Fetcher([req.repository])] + self._fetchers if req.repository else self._fetchers
    translator = ChainedTranslator(
      EggTranslator(install_cache=self._install_cache, platform=platform,
          python=interpreter.python),
      SourceTranslator(install_cache=self._install_cache, interpreter=interpreter,
          platform=platform, use_2to3=req.use_2to3))
    obtainer = Obtainer(self._crawler, fetchers, translator)
    return obtainer.obtain

  def resolve(self, requirements, interpreter=None):
    resolved = OrderedSet()
    requirements = list(requirements)
    for platform in self._platforms:
      for req in requirements:
        resolved.update(super(MultiResolver, self).resolve(req, platform=platform,
            interpreter=interpreter))
    return list(resolved)
