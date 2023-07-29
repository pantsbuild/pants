# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def main(version: str) -> str:
    maj, min = version.split(".")[:2]
    notes_path = Path("src/python/pants/notes", maj).with_suffix(f".{min}.x.md")
    notes_contents = notes_path.read_text()
    for section in notes_contents.split("\n## "):
        if section.startswith(version):
            section = section.replace("##", "#")
            return section.split("\n", 2)[-1]

    raise Exception(f"Couldn't find section for version {version} in {notes_path}")


if __name__ == "__main__":
    body = main(sys.argv[1])
    print(body)
