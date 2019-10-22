# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.contrib.go.targets.go_local_source import GoLocalSource


class GoModule(GoLocalSource):
  """A local go module-based package."""

  default_sources_globs = '**/*.go'

  @classmethod
  def alias(cls):
    return 'go_module'
