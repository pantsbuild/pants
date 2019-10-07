# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.contrib.go.targets.go_local_source import GoLocalSource


class GoLibrary(GoLocalSource):
  """A local Go package."""

  default_sources_globs = '*'
  default_sources_exclude_globs = ('BUILD', 'BUILD.*')

  @classmethod
  def alias(cls):
    return 'go_library'
