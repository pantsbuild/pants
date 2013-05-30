from twitter.common.lang import Compatibility
from twitter.pants.cache.combined_artifact_cache import CombinedArtifactCache
from twitter.pants.cache.file_based_artifact_cache import FileBasedArtifactCache
from twitter.pants.cache.restful_artifact_cache import RESTfulArtifactCache


def create_artifact_cache(context, artifact_root, spec):
  """Returns an artifact cache for the specified spec.

  If config is a string, it's interpreted as a path or URL prefix to a cache root. If it's a list of
  strings, it returns an appropriate combined cache.
  """
  if not spec:
    raise ValueError('Empty artifact cache spec')
  if isinstance(spec, Compatibility.string):
    if spec.startswith('/'):
      return FileBasedArtifactCache(context, artifact_root, spec)
    elif spec.startswith('http://') or spec.startswith('https://'):
      return RESTfulArtifactCache(context, artifact_root, spec)
    else:
      raise ValueError('Invalid artifact cache spec: %s' % spec)
  elif isinstance(spec, (list, tuple)):
    caches = [ create_artifact_cache(context, artifact_root, x) for x in spec ]
    return CombinedArtifactCache(caches)
