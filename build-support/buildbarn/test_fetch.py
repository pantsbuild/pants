# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import fetch


def write_manifest(tmp_path: Path, *, images: list[dict[str, object]]) -> Path:
    manifest_path = tmp_path / "images.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "images": images}), encoding="utf-8")
    return manifest_path


def completed_process(args: list[str], returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout="", stderr="")


def test_load_manifest_accepts_digest_pinned_references(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path,
        images=[
            {
                "name": "bb-storage",
                "reference": "ghcr.io/buildbarn/bb-storage:latest@sha256:"
                + "a" * 64,
                "required_for": ["cache"],
            }
        ],
    )

    images = fetch.load_manifest(manifest_path)

    assert images == (
        fetch.ImageSpec(
            name="bb-storage",
            reference=f"ghcr.io/buildbarn/bb-storage:latest@sha256:{'a' * 64}",
            required_for=("cache",),
        ),
    )


def test_load_manifest_rejects_unpinned_references(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path,
        images=[
            {
                "name": "bb-storage",
                "reference": "ghcr.io/buildbarn/bb-storage:latest",
                "required_for": ["cache"],
            }
        ],
    )

    with pytest.raises(fetch.FetchError, match="pinned by sha256 digest"):
        fetch.load_manifest(manifest_path)


def test_ensure_images_available_pulls_missing_images() -> None:
    commands: list[tuple[tuple[str, ...], bool]] = []

    def run_command(args: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        commands.append((tuple(args), check))
        if args[:3] == ["docker", "version", "--format"]:
            return completed_process(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return completed_process(args, returncode=1)
        if args[:2] == ["docker", "pull"]:
            return completed_process(args)
        raise AssertionError(f"Unexpected command: {args}")

    images = (
        fetch.ImageSpec(
            name="bb-storage",
            reference=f"ghcr.io/buildbarn/bb-storage:latest@sha256:{'b' * 64}",
            required_for=("cache",),
        ),
    )

    pulled = fetch.ensure_images_available(images, run_command=run_command)

    assert pulled == images
    assert commands == [
        (("docker", "version", "--format", "{{.Server.Version}}"), True),
        (("docker", "image", "inspect", f"ghcr.io/buildbarn/bb-storage:latest@sha256:{'b' * 64}"), False),
        (("docker", "pull", f"ghcr.io/buildbarn/bb-storage:latest@sha256:{'b' * 64}"), True),
    ]


def test_ensure_images_available_skips_local_images() -> None:
    commands: list[tuple[tuple[str, ...], bool]] = []

    def run_command(args: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        commands.append((tuple(args), check))
        if args[:3] == ["docker", "version", "--format"]:
            return completed_process(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return completed_process(args)
        raise AssertionError(f"Unexpected command: {args}")

    images = (
        fetch.ImageSpec(
            name="bb-storage",
            reference=f"ghcr.io/buildbarn/bb-storage:latest@sha256:{'c' * 64}",
            required_for=("cache",),
        ),
    )

    pulled = fetch.ensure_images_available(images, run_command=run_command)

    assert pulled == ()
    assert commands == [
        (("docker", "version", "--format", "{{.Server.Version}}"), True),
        (("docker", "image", "inspect", f"ghcr.io/buildbarn/bb-storage:latest@sha256:{'c' * 64}"), False),
    ]


def test_ensure_images_available_requires_docker() -> None:
    def run_command(args: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["docker", "version", "--format"]:
            raise FileNotFoundError("docker")
        raise AssertionError(f"Unexpected command: {args}")

    with pytest.raises(fetch.FetchError, match="Docker is required"):
        fetch.ensure_images_available((), run_command=run_command)
