# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import List

import requests

from pants.base.build_environment import get_pants_cachedir
from pants.core.util_rules.external_tool import ExternalTool, ExternalToolError
from pants.engine.platform import Platform


class CoursierSubsystem(ExternalTool):
    """Common configuration items for coursier tasks.

    :API: public
    """

    options_scope = "coursier"
    name = "coursier"
    default_version = "1.1.0.cf365ea27a710d5f09db1f0a6feee129aa1fc417"

    default_known_versions = [
        f"1.1.0.cf365ea27a710d5f09db1f0a6feee129aa1fc417|{plat}|24945c529eaa32a16a70256ac357108edc1b51a4dd45b656a1808c0cbf00617e|27573328"
        for plat in ["darwin", "linux"]
    ]

    _default_url = "https://github.com/coursier/coursier/releases/download/pants_release_1.5.x/coursier-cli-{version}.jar"

    class Error(Exception):
        """Indicates an error bootstrapping coursier."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--cache-dir",
            type=str,
            fingerprint=True,
            default=os.path.join(get_pants_cachedir(), "coursier"),
            help="Version paired with --bootstrap-jar-url, in order to invalidate and fetch the new version.",
        )
        register(
            "--repos",
            type=list,
            fingerprint=True,
            help="Maven style repos",
            default=[
                "https://maven-central.storage-download.googleapis.com/maven2",
                "https://repo1.maven.org/maven2",
            ],
        )
        register(
            "--fetch-options",
            type=list,
            fingerprint=True,
            default=[
                # Quiet mode, so coursier does not show resolve progress,
                # but still prints results if --report is specified.
                "-q",
                # Do not use default public maven repo.
                "--no-default",
                # Concurrent workers
                "-n",
                "8",
            ],
            help="Additional options to pass to coursier fetch. See `coursier fetch --help`",
        )
        register(
            "--artifact-types",
            type=list,
            fingerprint=True,
            default=["jar", "bundle", "test-jar", "maven-plugin", "src", "doc"],
            help="Specify the type of artifacts to fetch. See `packaging` at https://maven.apache.org/pom.html#Maven_Coordinates, "
            "except `src` and `doc` being coursier specific terms for sources and javadoc.",
        )
        # TODO(yic): Use a published version of Coursier. https://github.com/pantsbuild/pants/issues/6852
        register(
            "--bootstrap-jar-urls",
            fingerprint=True,
            type=list,
            default=[cls._default_url],
            help="Locations to download a bootstrap version of Coursier from.",
        )

    def generate_url(self, plat: Platform) -> str:
        # We need to pick one URL to return, so we check for the first one that returns a
        # 200 for a HEAD request.
        # TODO: Allow ExternalTool to handle multiple URLs itself? May be overkill.
        #  It's not even clear that this subsystem really needs to do so.
        version = self.get_options().version
        urls_to_try: List[str] = [
            url.format(version=version) for url in self.get_options().bootstrap_jar_urls
        ]
        for url in urls_to_try:
            if requests.head(url).ok:
                return url
        raise ExternalToolError()  # Calling code will generate a sensible error message.
