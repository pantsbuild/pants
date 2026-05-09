# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest
import yaml

from pants.backend.codegen.protobuf.buf.config import (
    UnpinnedBufPluginError,
    parse_buf_yaml_deps,
    parse_plugin_outs,
    suffix_plugin_includes_imports,
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


def test_synthesize_overrides_partial_pin_with_registry_default() -> None:
    """A version-only pin (no `revision:`) gets overridden with the registry's full
    pin so the entry is unambiguous."""
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python:v33.0
            out: gen
        """
    ).encode("utf-8")
    out = synthesize_pinned_buf_gen_yaml(content, "buf.gen.yaml")
    [plugin] = _plugins(out)
    assert "revision" in plugin
    # Registry default version replaces the user's version-only pin.
    assert plugin["remote"] != "buf.build/protocolbuffers/python:v33.0"


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


def test_synthesize_ignores_malformed_extra_pin_string() -> None:
    """Malformed `extra_pins` values (missing `:revN`) are silently dropped, so the
    plugin is treated as unknown-and-unpinned and raises."""
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: example.com/some/custom-plugin
            out: gen
        """
    ).encode("utf-8")
    with pytest.raises(UnpinnedBufPluginError):
        synthesize_pinned_buf_gen_yaml(
            content,
            "buf.gen.yaml",
            extra_pins={"example.com/some/custom-plugin": "no-colon"},
        )


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


def test_suffix_plugin_includes_imports_true_for_remote() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python
            out: gen
            include_imports: true
        """
    ).encode("utf-8")
    suffixes = {"remote:buf.build/protocolbuffers/python": "_pb2"}
    assert suffix_plugin_includes_imports(content, "_pb2", suffixes) is True


def test_suffix_plugin_includes_imports_false_when_unset() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python
            out: gen
        """
    ).encode("utf-8")
    suffixes = {"remote:buf.build/protocolbuffers/python": "_pb2"}
    assert suffix_plugin_includes_imports(content, "_pb2", suffixes) is False


def test_suffix_plugin_includes_imports_only_checks_matching_suffix() -> None:
    """`include_imports` on a different-suffix plugin doesn't bleed over."""
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/pyi
            out: gen
            include_imports: true
          - remote: buf.build/protocolbuffers/python
            out: gen
        """
    ).encode("utf-8")
    suffixes = {
        "remote:buf.build/protocolbuffers/pyi": "_pb2.pyi",
        "remote:buf.build/protocolbuffers/python": "_pb2",
    }
    assert suffix_plugin_includes_imports(content, "_pb2", suffixes) is False


def test_suffix_plugin_includes_imports_tolerates_pinned_remote() -> None:
    content = dedent(
        """\
        version: v2
        plugins:
          - remote: buf.build/protocolbuffers/python:v34.1
            revision: 1
            out: gen
            include_imports: true
        """
    ).encode("utf-8")
    suffixes = {"remote:buf.build/protocolbuffers/python": "_pb2"}
    assert suffix_plugin_includes_imports(content, "_pb2", suffixes) is True


def test_suffix_plugin_includes_imports_works_for_protoc_builtin() -> None:
    """`include_imports` is a buf-level switch, applicable to `protoc_builtin:`
    plugins identically — not just `remote:` ones."""
    content = dedent(
        """\
        version: v2
        plugins:
          - protoc_builtin: python
            out: gen
            include_imports: true
        """
    ).encode("utf-8")
    suffixes = {"protoc_builtin:python": "_pb2"}
    assert suffix_plugin_includes_imports(content, "_pb2", suffixes) is True
