# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform
from pants.util.enums import match


class CargoFetcher(ExternalTool):
    """A tool to resolve 3rdparty rust dependencies from Cargo.lock files."""
    options_scope = 'cargo-fetcher'
    default_version = '0.8.0'
    default_known_versions = [
        "0.8.0|darwin|d4ebee3d2e234544702c7ad46e4b339789e2af66f84569a6d72a036572cf6c27|4246990",
        "0.8.0|linux|cc3208dcee41a027a95e360a540d1cafd979bd772fcbd51e9698bd02025f86e6|4661451",
    ]

    @staticmethod
    def platform_descriptor(plat: Platform) -> str:
        return match(plat, {
            Platform.darwin: 'x86_64-apple-darwin',
            Platform.linux: 'x86_64-unknown-linux-musl',
        })

    def generate_url(self, plat: Platform) -> str:
        version = self.options.version
        platform_descriptor = self.platform_descriptor(plat)
        return f"https://github.com/EmbarkStudios/cargo-fetcher/releases/download/{version}/cargo-fetcher-{version}-{platform_descriptor}.tar.gz"

    def generate_exe(self, plat: Platform) -> str:
        version = self.options.version
        platform_descriptor = self.platform_descriptor(plat)
        return f"cargo-fetcher-{version}-{platform_descriptor}/cargo-fetcher"
