# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Iterator

from pkg_resources import Requirement


def load_requirements(content: str) -> Iterator[tuple[str, int]]:
    """Loads all lines from a requirements.txt-style file.

    This will safely ignore any options starting with `--` and will ignore comments. Any pip-style
    VCS requirements will fail, with a helpful error message describing how to use PEP 440.
    """
    for i, line in enumerate(content.splitlines(), start=1):
        line, _, _ = line.partition("--")
        line = line.strip().rstrip("\\")
        if not line or line.startswith(("#", "-")):
            continue

        yield str(Requirement.parse(line)), i
