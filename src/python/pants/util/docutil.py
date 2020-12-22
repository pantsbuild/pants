# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.version import MAJOR_MINOR


def docs_url(slug: str) -> str:
    """Link to the Pants docs using the current version of Pants."""
    return f"https://www.pantsbuild.org/v{MAJOR_MINOR}/docs/{slug}"
