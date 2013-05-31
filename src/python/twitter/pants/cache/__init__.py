import urlparse
from twitter.pants.cache.pinger import Pinger
from twitter.pants.cache.combined_artifact_cache import CombinedArtifactCache
from twitter.pants.cache.file_based_artifact_cache import FileBasedArtifactCache
from twitter.pants.cache.restful_artifact_cache import RESTfulArtifactCache


def select_best_url(spec, pinger, log):
  urls = spec.split('|')
  hosts = map(lambda url: urlparse.urlparse(url)[1].split(':')[0], urls)
  pingtimes = pinger.pings(hosts)  # List of pairs (host, time in ms).
  log.info('Artifact cache server ping times: %s' %
                   ', '.join(['%s: %3f ms' % p for p in pingtimes]))
  argmin = min(xrange(len(pingtimes)), key=lambda i: pingtimes[i][1])
  best_url = urls[argmin]
  log.info('Selecting artifact cache at %s' % best_url)
  return best_url

def create_artifact_cache(log, artifact_root, spec):
  """Returns an artifact cache for the specified spec.

  spec can be:
    - a path to a file-based cache root.
    - a URL of a RESTful cache root.
    - a bar-separated list of URLs, where we'll pick the one with the best ping times.
    - A list of the above, for a combined cache.
  """
  if not spec:
    raise ValueError('Empty artifact cache spec')
  if isinstance(spec, basestring):
    if spec.startswith('/'):
      return FileBasedArtifactCache(log, artifact_root, spec)
    elif spec.startswith('http://') or spec.startswith('https://'):
      return RESTfulArtifactCache(log, artifact_root, select_best_url(spec, Pinger(), log))
    else:
      raise ValueError('Invalid artifact cache spec: %s' % spec)
  elif isinstance(spec, (list, tuple)):
    caches = [ create_artifact_cache(log, artifact_root, x) for x in spec ]
    return CombinedArtifactCache(caches)
