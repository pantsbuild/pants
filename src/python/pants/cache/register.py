# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Advanced support for the V1 caching mechanism, such as enabling retries of failed downloads."""

from pants.cache.restful_artifact_cache import RequestsSession


def global_subsystems():
    return {RequestsSession.Factory}
