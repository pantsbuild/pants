import urlparse
from twitter.pants.cache.pinger import Pinger
from twitter.pants.cache.combined_artifact_cache import CombinedArtifactCache
from twitter.pants.cache.file_based_artifact_cache import FileBasedArtifactCache
from twitter.pants.cache.restful_artifact_cache import RESTfulArtifactCache


def select_best_url(spec, pinger, log):
  urls = spec.split('|')
  if len(urls) == 1:
    return urls[0]  # No need to ping if we only have one option anyway.
  netlocs = map(lambda url: urlparse.urlparse(url)[1], urls)
  pingtimes = pinger.pings(netlocs)  # List of pairs (host, time in ms).
  log.debug('Artifact cache server ping times: %s' %
            ', '.join(['%s: %3f ms' % p for p in pingtimes]))
  argmin = min(xrange(len(pingtimes)), key=lambda i: pingtimes[i][1])
  best_url = urls[argmin]
  if pingtimes[argmin] == Pinger.UNREACHABLE:
    return None  # No reachable artifact caches.
  log.debug('Best artifact cache is %s' % best_url)
  return best_url


def create_artifact_cache(log, artifact_root, spec, task_name):
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
      log.info('%s using local artifact cache at %s' % (task_name, spec))
      return FileBasedArtifactCache(log, artifact_root, spec)
    elif spec.startswith('http://') or spec.startswith('https://'):
      # Caches are supposed to be close, and we don't want to waste time pinging on no-op builds.
      # So we ping twice with a short timeout.
      pinger = Pinger(timeout=0.5, tries=2)
      best_url = select_best_url(spec, pinger, log)
      if best_url:
        log.info('%s using remote artifact cache at %s' % (task_name, best_url))
        return RESTfulArtifactCache(log, artifact_root, best_url)
      else:
        log.warn('No reachable artifact cache in %s.' % spec)
        return None
    else:
      raise ValueError('Invalid artifact cache spec: %s' % spec)
  elif isinstance(spec, (list, tuple)):
    caches = [ create_artifact_cache(log, artifact_root, x, task_name) for x in spec ]
    return CombinedArtifactCache(caches)
