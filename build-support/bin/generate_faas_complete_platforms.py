# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from pants.backend.awslambda.python.target_types import PythonAwsLambdaRuntime
from pants.backend.python.util_rules.faas import PythonFaaSRuntimeField
from pants.base.build_environment import get_buildroot

COMMAND = "pip install pex 1>&2 && pex3 interpreter inspect --markers --tags"


RUNTIME_FIELDS = [
    PythonAwsLambdaRuntime,
    # TODO: what docker images to use for GCF?
]


def extract_complete_platform(repo: str, tag: str) -> object:
    image = f"{repo}:{tag}"
    print(f"Extracting complete platform for {image}", file=sys.stderr)
    result = subprocess.run(
        ["docker", "run", "--entrypoint", "sh", image, "-c", COMMAND],
        check=True,
        stdout=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def run(runtime_field: type[PythonFaaSRuntimeField], python_base: Path) -> None:
    cp_dir = python_base / runtime_field.known_runtimes_complete_platforms_module().replace(
        ".", "/"
    )
    print(f"Generating for {runtime_field.__name__}, writing to {cp_dir}", file=sys.stderr)
    for rt in runtime_field.known_runtimes:
        cp = extract_complete_platform(runtime_field.known_runtimes_docker_repo, rt.tag)

        fname = cp_dir / rt.file_name()
        with fname.open("w") as f:
            json.dump(cp, f, indent=2)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generates the complete platform JSON files for AWS Lambda and GCF"
    )
    return parser


def main() -> None:
    create_parser().parse_args()

    build_root = Path(get_buildroot()) / "src/python"
    for runtime_field in RUNTIME_FIELDS:
        run(runtime_field, build_root)


if __name__ == "__main__":
    main()
