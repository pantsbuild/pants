# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: This script requires that the underlying docker installation
# has `buildx` support, and also that the underlying system has
# QEMU installed so that Docker can run images of a different
# architecture.

# This script can be run via `pants run`, but it needs to be run
# with the `--no-watch-filesystem` flag, because the contents of the
# `awslambda` backend depend on the resources generated by this script.
# If run without the `--no-watch-filesystem` flag, the script will
# loop infinitely, because it restarts itself whenever the output files
# change (FIXME #21243).
#
# Command: pants --no-watch-filesystem run build-support/bin/generate_faas_complete_platforms.py

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pants.backend.awslambda.python.target_types import PythonAwsLambdaRuntime
from pants.backend.python.util_rules.faas import FaaSArchitecture, PythonFaaSRuntimeField
from pants.base.build_environment import get_buildroot

COMMAND = "pip install pex 1>&2 && pex3 interpreter inspect --markers --tags"


RUNTIME_FIELDS = [
    PythonAwsLambdaRuntime,
    # TODO: what docker images to use for GCF?
]


def extract_complete_platform(repo: str, architecture: FaaSArchitecture, tag: str) -> object:
    image = f"{repo}:{tag}"
    docker_platform = "linux/amd64" if architecture == FaaSArchitecture.X86_64 else "linux/arm64"
    print(
        f"Extracting complete platform for {image} on platform {docker_platform}", file=sys.stderr
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--platform",
            docker_platform,
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            COMMAND,
        ],
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
        cp = extract_complete_platform(
            runtime_field.known_runtimes_docker_repo,
            FaaSArchitecture(rt.architecture) if rt.architecture else FaaSArchitecture.X86_64,
            rt.tag,
        )

        fname = cp_dir / rt.file_name()
        with fname.open("w") as f:
            json.dump(cp, f, indent=2)


def main() -> None:
    build_root = Path(get_buildroot()) / "src/python"
    for runtime_field in RUNTIME_FIELDS:
        run(runtime_field, build_root)


if __name__ == "__main__":
    main()
