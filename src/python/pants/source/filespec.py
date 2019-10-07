# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.fs import PathGlobs
from pants.engine.native import Native


def globs_matches(paths, patterns, exclude_patterns):
  path_globs = PathGlobs(include=patterns, exclude=exclude_patterns)
  return Native().match_path_globs(path_globs, paths)


def matches_filespec(path, spec):
  return any_matches_filespec([path], spec)


def any_matches_filespec(paths, spec):
  exclude_patterns = []
  for exclude_spec in spec.get('exclude', []):
    exclude_patterns.extend(exclude_spec.get('globs', []))
  return globs_matches(paths, spec.get('globs', []), exclude_patterns)
