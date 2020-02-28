# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator

logger = logging.getLogger(__name__)


class YarnReleaseUrlGenerator(BinaryToolUrlGenerator):

    _DIST_URL_FMT = (
        "https://github.com/yarnpkg/yarn/releases/download/{version}/yarn-{version}.tar.gz"
    )

    def generate_urls(self, version, host_platform):
        return [self._DIST_URL_FMT.format(version=version)]


class YarnpkgDistribution(NativeTool):
    """Represents a self-bootstrapping Yarnpkg distribution."""

    options_scope = "yarnpkg-distribution"
    name = "yarnpkg"
    default_version = "v1.6.0"
    archive_type = "tgz"

    def get_external_url_generator(self):
        return YarnReleaseUrlGenerator()
