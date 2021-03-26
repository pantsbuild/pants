# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shutil

from pants.version import MAJOR_MINOR


# NB: This is not memoized because that would cause Pants to not pick up terminal resizing when
# using pantsd.
def terminal_width(*, fallback: int = 96, padding: int = 2) -> int:
    return shutil.get_terminal_size(fallback=(fallback, 24)).columns - padding


def bracketed_docs_url(slug: str) -> str:
    """Link to the Pants docs using the current version of Pants.

    Returned URL is surrounded by square brackets, to prevent linkifiers from considering any
    adjacent punctuation (such as a period at the end of a sentence) as part of the URL.
    """
    return f"[https://www.pantsbuild.org/v{MAJOR_MINOR}/docs/{slug}]"
