# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.cache.restful_artifact_cache import RequestsSession


def global_subsystems():
  return {RequestsSession.Factory}
