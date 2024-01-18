# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

vcs_version(
    name="generated-version",
    generate_to="pants/_version/VERSION",
    # @TODO: This won't be as meaningful on `main`, as the dev number gets replaced with the "distance".
    #   However, of all of the schemes the `-semver` ones are the only ones that allow for `.devN`
    #   tags, and produce a valid version. "release-branch-semver" increments minor version which is
    #   more misleading than "python-simplified-semver" which increments patch.
    #   Use https://github.com/pypa/setuptools_scm/pull/1005 when we can.
    version_scheme="python-simplified-semver",
    local_scheme="no-local-version" if env("CI", "0") == "1" else None,
    tag_regex=r"^release_(?P<version>[vV]?\d+(?:\.\d+){0,2}[^\+]*)$",
    template="{version}",
)

experimental_wrap_as_resources(name="VERSION", inputs=[":generated-version"])
