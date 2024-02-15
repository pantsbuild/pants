# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

# NB: Keep in sync with `src/python/pants/version.py`
vcs_version(
    name="generated-version",
    generate_to="pants/_version/VERSION",
    # NB: The scheme we use on CI (e.g. when we've checked out a tagged commit) should be irrelevant
    #   as all schemes will just use the tag when on a tagged commit.
    version_scheme="only-version",
    # NB: Don't dirty the version in CI
    local_scheme="no-local-version" if env("CI", "0") == "1" else None,
    tag_regex=r"^release_(?P<version>[vV]?\d+(?:\.\d+){0,2}[^\+]*)$",
    template="{version}",
)

experimental_wrap_as_resources(name="VERSION", inputs=[":generated-version"])
