# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Iterator

from pants.util.pip_requirement import PipRequirement


def parse_requirements_file(content: str, *, rel_path: str) -> Iterator[PipRequirement]:
    """Parse all `PipRequirement` objects from a requirements.txt-style file.

    This will safely ignore any options starting with `--` and will ignore comments. Any pip-style
    VCS requirements will fail, with a helpful error message describing how to use PEP 440.
    """
    for i, line in enumerate(content.splitlines(), start=1):
        line, _, _ = line.partition("--")
        line = line.strip().rstrip("\\")
        if not line or line.startswith(("#", "-")):
            continue

        # Strip comments which are othewise on a valid requirement line.
        comment_pos = line.find("#")
        if comment_pos != -1:
            line = line[0:comment_pos].strip()

        yield PipRequirement.parse(line, description_of_origin=f"{rel_path} at line {i}")
