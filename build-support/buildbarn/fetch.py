# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
import re

DEFAULT_MANIFEST_PATH = Path(__file__).with_name("images.json")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class FetchError(ValueError):
    pass


@dataclass(frozen=True)
class ImageSpec:
    name: str
    reference: str
    required_for: tuple[str, ...]

    @property
    def repository(self) -> str:
        return parse_image_reference(self.reference).repository


@dataclass(frozen=True)
class ImageReference:
    repository: str
    tag: str
    digest: str


RunCommand = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]


def parse_image_reference(reference: str) -> ImageReference:
    tagged_repository, separator, digest = reference.partition("@")
    tag_separator_index = tagged_repository.rfind(":")
    slash_index = tagged_repository.rfind("/")
    if tag_separator_index <= slash_index:
        raise FetchError(f"Image reference must include a tag before the digest: {reference}")

    if separator != "@" or not _DIGEST_RE.match(digest):
        raise FetchError(f"Image reference must be pinned by sha256 digest: {reference}")

    repository = tagged_repository[:tag_separator_index]
    tag = tagged_repository[tag_separator_index + 1 :]
    if not repository or not tag:
        raise FetchError(f"Image reference must include a repository and tag: {reference}")

    return ImageReference(repository=repository, tag=tag, digest=digest)


def load_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> tuple[ImageSpec, ...]:
    with manifest_path.open(encoding="utf-8") as fp:
        data = json.load(fp)

    if data.get("schema_version") != 1:
        raise FetchError(
            f"Unsupported Buildbarn image manifest schema version in {manifest_path}: "
            f"{data.get('schema_version')!r}"
        )

    images = data.get("images")
    if not isinstance(images, list) or not images:
        raise FetchError(f"Buildbarn image manifest must contain a non-empty images list: {manifest_path}")

    loaded: list[ImageSpec] = []
    seen_names: set[str] = set()
    for image_data in images:
        name = image_data.get("name")
        reference = image_data.get("reference")
        required_for = image_data.get("required_for")
        if not isinstance(name, str) or not name:
            raise FetchError(f"Every Buildbarn image must have a non-empty name: {image_data!r}")
        if name in seen_names:
            raise FetchError(f"Buildbarn image names must be unique, but {name!r} is duplicated")
        if not isinstance(reference, str):
            raise FetchError(f"Buildbarn image {name!r} must provide a string reference")
        if not isinstance(required_for, list) or not required_for or not all(
            isinstance(mode, str) and mode for mode in required_for
        ):
            raise FetchError(
                f"Buildbarn image {name!r} must provide a non-empty required_for list of strings"
            )

        parse_image_reference(reference)
        loaded.append(ImageSpec(name=name, reference=reference, required_for=tuple(required_for)))
        seen_names.add(name)

    return tuple(loaded)


def ensure_images_available(
    images: Iterable[ImageSpec],
    *,
    pull: bool = True,
    docker_binary: str = "docker",
    run_command: RunCommand | None = None,
) -> tuple[ImageSpec, ...]:
    runner = run_command or _run_command
    _ensure_docker_available(docker_binary=docker_binary, run_command=runner)

    pulled_images: list[ImageSpec] = []
    for image in images:
        if _image_exists(image.reference, docker_binary=docker_binary, run_command=runner):
            continue
        if not pull:
            raise FetchError(f"Docker image is not available locally: {image.reference}")
        runner([docker_binary, "pull", image.reference], True)
        pulled_images.append(image)

    return tuple(pulled_images)


def _ensure_docker_available(*, docker_binary: str, run_command: RunCommand) -> None:
    try:
        run_command([docker_binary, "version", "--format", "{{.Server.Version}}"], True)
    except FileNotFoundError as error:
        raise FetchError("Docker is required for Buildbarn integration tests, but was not found") from error
    except subprocess.CalledProcessError as error:
        raise FetchError(
            "Docker is required for Buildbarn integration tests, but `docker version` failed: "
            f"{error.stderr.strip() or error.stdout.strip() or error}"
        ) from error


def _image_exists(reference: str, *, docker_binary: str, run_command: RunCommand) -> bool:
    result = run_command([docker_binary, "image", "inspect", reference], False)
    return result.returncode == 0


def _run_command(args: Sequence[str], check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and fetch pinned Buildbarn Docker images.")
    parser.add_argument(
        "command",
        choices=["check", "ensure", "list"],
        nargs="?",
        default="ensure",
        help="`check` validates the manifest, `ensure` also pulls missing images, and `list` prints image refs.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to the checked-in Buildbarn image manifest.",
    )
    parser.add_argument(
        "--docker-binary",
        default="docker",
        help="Docker CLI binary to invoke.",
    )
    parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Fail instead of pulling when an image is missing locally.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = create_parser().parse_args(argv)
    images = load_manifest(options.manifest)

    if options.command == "list":
        for image in images:
            print(image.reference)
        return 0

    if options.command == "check":
        return 0

    ensure_images_available(
        images,
        pull=not options.no_pull,
        docker_binary=options.docker_binary,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
