# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest
import yaml

from pants.backend.codegen.protobuf.buf.config import (
    InvalidBufPluginPinError,
    UnpinnedBufPluginError,
    UnsupportedBufGenYamlVersionError,
    parse_buf_yaml_deps,
    parse_plugin_outs,
    synthesize_pinned_buf_gen_yaml,
)


def _plugins(content: bytes) -> list[dict]:
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)
    plugins = parsed["plugins"]
    assert isinstance(plugins, list)
    return plugins


def test_synthesize_keeps_already_pinned_entry_unchanged() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python:v34.1
            revision: 1
            out: gen
        """
    ).encode("utf-8")
    out = synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml")
    # Already fully pinned → returned unchanged byte-for-byte.
    assert out == content


def test_synthesize_fills_in_pin_for_known_unpinned_plugin() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python
            out: gen
        """
    ).encode("utf-8")
    out = synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml")
    [plugin] = _plugins(out)
    # Registry default for protocolbuffers/python kicks in.
    assert plugin["remote"].startswith("buf.build/protocolbuffers/python:v")
    assert isinstance(plugin["revision"], int) and plugin["revision"] >= 1


def test_synthesize_fills_in_revision_for_registry_version() -> None:
    """A version-only pin gets the registry's revision when the versions match."""
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python:v34.1
            out: gen
        """
    ).encode("utf-8")
    [plugin] = _plugins(synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml"))
    assert plugin["remote"] == "buf.build/protocolbuffers/python:v34.1"
    assert plugin["revision"] == 1


@pytest.mark.parametrize(
    "entry, reason",
    [
        # A version the registry doesn't pin: the user's choice is kept, not replaced.
        ("remote: buf.build/protocolbuffers/python:v33.0", "needs a `revision:`"),
        ("remote: buf.build/protocolbuffers/python\n    revision: 1", "but no version"),
    ],
    ids=["unknown-version", "revision-only"],
)
def test_synthesize_rejects_partial_pin(entry: str, reason: str) -> None:
    content = f"version: v2\nplugins:\n  - {entry}\n    out: gen\n".encode()
    with pytest.raises(UnpinnedBufPluginError, match=reason):
        synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml")


def test_synthesize_raises_for_unknown_unpinned_plugin() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: example.com/some/custom-plugin
            out: gen
        """
    ).encode("utf-8")
    with pytest.raises(UnpinnedBufPluginError) as excinfo:
        synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml")
    assert "example.com/some/custom-plugin" in str(excinfo.value)


def test_synthesize_accepts_user_provided_extra_pins() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: example.com/some/custom-plugin
            out: gen
        """
    ).encode("utf-8")
    out = synthesize_pinned_buf_gen_yaml(
        content,
        "buf.gen.yaml",
        extra_pins={"example.com/some/custom-plugin": "v2.0:3"},
    )
    [plugin] = _plugins(out)
    assert plugin["remote"] == "example.com/some/custom-plugin:v2.0"
    assert plugin["revision"] == 3


def test_synthesize_extra_pins_override_registry_default() -> None:
    """A user `extra_pins` entry for a plugin already in the registry overrides
    the registry default."""
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python
            out: gen
        """
    ).encode("utf-8")
    out = synthesize_pinned_buf_gen_yaml(
        content,
        "buf.gen.yaml",
        extra_pins={"buf.build/protocolbuffers/python": "v99.0:7"},
    )
    [plugin] = _plugins(out)
    assert plugin["remote"] == "buf.build/protocolbuffers/python:v99.0"
    assert plugin["revision"] == 7


@pytest.mark.parametrize("pin", ["no-colon", "v2.0:rev3", ":3", "v2.0:3:4"])
def test_synthesize_rejects_malformed_extra_pin_string(pin: str) -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: example.com/some/custom-plugin
            out: gen
        """
    ).encode("utf-8")
    with pytest.raises(InvalidBufPluginPinError, match="example.com/some/custom-plugin"):
        synthesize_pinned_buf_gen_yaml(
            content,
            "buf.gen.yaml",
            extra_pins={"example.com/some/custom-plugin": pin},
        )


@pytest.mark.parametrize("version_line", ["version: v1\n", "version: v1beta1\n", ""])
def test_synthesize_rejects_non_v2_template(version_line: str) -> None:
    content = (
        f"{version_line}plugins:\n  - plugin: buf.build/protocolbuffers/python\n    out: gen\n"
    ).encode()
    with pytest.raises(UnsupportedBufGenYamlVersionError, match="buf config migrate"):
        synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml")


def test_synthesize_ignores_protoc_builtin_and_local() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - protoc_builtin: python
            out: gen
          - local: protoc-gen-foo
            out: gen
        """
    ).encode("utf-8")
    # No `remote:` entries → no synthesis, no error.
    assert synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml") == content


def test_parse_plugin_outs_strips_remote_version_for_lookup() -> None:
    """`remote:` matching is version-tolerant — pinned and unpinned both land in the
    caller-supplied suffixes dict."""
    suffixes = {"remote:buf.build/protocolbuffers/python": "_pb2"}
    pinned = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python:v34.1
            revision: 1
            out: gen
        """
    ).encode("utf-8")
    unpinned = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python
            out: gen
        """
    ).encode("utf-8")
    assert parse_plugin_outs(pinned, suffixes) == {"_pb2": "gen"}
    assert parse_plugin_outs(unpinned, suffixes) == {"_pb2": "gen"}


def test_parse_buf_yaml_deps_extracts_module_ids() -> None:
    content = dedent(
        """\
        version: v2
        modules:
          - path: idl
        deps:
          - buf.build/bufbuild/protovalidate
          - buf.build/googleapis/googleapis
        """
    ).encode("utf-8")
    assert parse_buf_yaml_deps(content) == (
        "buf.build/bufbuild/protovalidate",
        "buf.build/googleapis/googleapis",
    )


def test_parse_buf_yaml_deps_returns_empty_for_missing_or_invalid() -> None:
    no_deps = dedent("version: v2\nmodules:\n  - path: idl\n").encode("utf-8")
    assert parse_buf_yaml_deps(no_deps) == ()
    assert parse_buf_yaml_deps(b"not: valid: yaml: ::\nx") == ()
    assert parse_buf_yaml_deps(b"") == ()
