# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Shared, language-agnostic helpers for working with `buf.yaml` and `buf.gen.yaml`.

These primitives are used by the per-language buf integrations so each language
only owns its own suffix conventions and module-name math, not yaml parsing
or plugin matching.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import yaml

from pants.backend.codegen.protobuf.buf.fields import BufGenTemplateField
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.core.util_rules.config_files import ConfigFilesRequest, find_config_file
from pants.engine.intrinsics import get_digest_contents
from pants.engine.rules import concurrently
from pants.engine.target import Target

# ---- Errors ----------------------------------------------------------------


class UnpinnedBufPluginError(Exception):
    """Raised when a `remote:` plugin entry is missing a version+revision pin and
    isn't in the user's `DEFAULT_PLUGIN_PINS` registry."""


class MissingBufLockError(Exception):
    """Raised when `buf.yaml` declares `deps:` but no sibling `buf.lock` exists."""


# ---- Default plugin-pin registry -------------------------------------------


# Default `(version, revision)` pin Pants will fill in for known `remote:`
# plugins that the user wrote without a pin or revision. The synthesized
# `buf.gen.yaml` entry has the form:
#
#     - remote: <id>:<version>
#       revision: <revision>
#       out: ...
#
# These values are the latest as of writing, fetched from the BSR's
# `PluginCurationService.GetLatestCuratedPlugin` endpoint. To refresh:
#
#     curl -X POST \
#       https://buf.build/buf.alpha.registry.v1alpha1.PluginCurationService/GetLatestCuratedPlugin \
#       -H 'Content-Type: application/json' -H 'Connect-Protocol-Version: 1' \
#       -d '{"owner":"<owner>","name":"<plugin>"}'
#
# The browseable equivalent is https://buf.build/<owner>/<plugin> — each
# plugin's "Versions" tab lists every `(version, revision)` pair available.
# Bumping a pin is a one-line change here; cache invalidation is automatic
# via the synthesized `buf.gen.yaml`'s content hash.
DEFAULT_PLUGIN_PINS: Mapping[str, tuple[str, int]] = {
    "buf.build/protocolbuffers/python": ("v34.1", 1),
    "buf.build/protocolbuffers/pyi": ("v34.1", 1),
    "buf.build/connectrpc/python": ("v0.10.0", 1),
    "buf.build/grpc/python": ("v1.80.0", 1),
}


# ---- buf.yaml parsers ------------------------------------------------------


def parse_buf_yaml_module_paths(content: bytes) -> tuple[str, ...]:
    """Module paths declared in a v2 `buf.yaml`, relative to the file.

    Returns `()` for v1 `buf.yaml` (no `modules:` block); callers should treat the
    file's own directory as the implicit module root in that case.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return ()
    if not isinstance(data, dict):
        return ()
    modules = data.get("modules")
    if not isinstance(modules, list):
        return ()
    paths: list[str] = []
    for entry in modules:
        if isinstance(entry, dict):
            p = entry.get("path")
            if isinstance(p, str) and p:
                paths.append(p)
    return tuple(paths)


def parse_buf_yaml_deps(content: bytes) -> tuple[str, ...]:
    """BSR module IDs declared in a `buf.yaml`'s `deps:` list."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return ()
    if not isinstance(data, dict):
        return ()
    deps = data.get("deps")
    if not isinstance(deps, list):
        return ()
    return tuple(d for d in deps if isinstance(d, str) and d)


def resolve_buf_module_root(
    proto_path: str, buf_yaml_dir: str, module_paths: tuple[str, ...]
) -> str:
    """Resolve the buf module root for a proto file.

    `buf_yaml_dir` is the directory holding `buf.yaml`. `module_paths` are the
    entries from its `modules:` list (relative to that directory). The returned
    root is the longest configured module path that contains the proto, normalized
    to the repo root.
    """
    if not module_paths:
        return buf_yaml_dir
    candidates = sorted(
        (os.path.normpath(os.path.join(buf_yaml_dir, p)) for p in module_paths),
        key=len,
        reverse=True,
    )
    for root in candidates:
        if root == "." or root == "":
            return ""
        if proto_path == root or proto_path.startswith(root + os.sep):
            return root
    return candidates[0]


# ---- buf.gen.yaml parsers --------------------------------------------------


def _plugin_identifier(plugin: dict) -> str | None:
    """Return the registry key (`"<kind>:<ident>"`) for a `buf.gen.yaml` plugin entry.

    `kind` is one of `protoc_builtin`, `local`, or `remote` — matching the field
    name in the entry. `ident` strips any `:vX.Y` version pin from `remote:` so
    callers can match against the registry without knowing the version. Returns
    `None` if the entry declares none of these fields.
    """
    for key in ("protoc_builtin", "local", "remote"):
        val = plugin.get(key)
        if val is None:
            continue
        ident = " ".join(str(x) for x in val) if isinstance(val, list) else str(val)
        if key == "remote":
            base, _, _ = ident.partition(":")
            return f"remote:{base}"
        return f"{key}:{ident}"
    return None


def parse_plugin_outs(content: bytes, suffixes: Mapping[str, str]) -> dict[str, str]:
    """Walk `buf.gen.yaml` plugins and return `suffix -> out:` for matching entries.

    `suffixes` is a `<kind>:<ident> -> suffix` dict supplied by the calling
    language backend, where `<kind>` is `remote`, `protoc_builtin`, or `local`
    and `suffix` is the language's module/file-naming suffix. The first matching
    plugin per suffix wins.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return {}

    result: dict[str, str] = {}
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        out = plugin.get("out")
        if not isinstance(out, str) or not out:
            continue
        key = _plugin_identifier(plugin)
        if key is None:
            continue
        suffix = suffixes.get(key)
        if suffix is not None and suffix not in result:
            result[suffix] = out
    return result


def suffix_plugin_includes_imports(
    content: bytes, suffix: str, suffixes: Mapping[str, str]
) -> bool:
    """True if the `buf.gen.yaml` plugin emitting `suffix` has `include_imports:
    true` set — meaning buf will materialize generated artifacts for
    transitively-imported BSR-dep protos into the digest.

    `suffixes` is the same `<kind>:<ident> -> suffix` mapping passed to
    `parse_plugin_outs`; the first plugin entry whose registry key maps to
    `suffix` wins.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict):
        return False
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return False
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        out = plugin.get("out")
        if not isinstance(out, str) or not out:
            continue
        key = _plugin_identifier(plugin)
        if key is None:
            continue
        if suffixes.get(key) != suffix:
            continue
        return plugin.get("include_imports") is True
    return False


# ---- buf.gen.yaml pin synthesis --------------------------------------------


def _split_remote_ident(ident: str) -> tuple[str, str | None]:
    """Split a `remote:` value into `(base_id, version_or_None)`.

    `buf.build/foo/bar:v1.2` → (`buf.build/foo/bar`, `v1.2`).
    `buf.build/foo/bar` → (`buf.build/foo/bar`, None).
    """
    base, sep, suffix = ident.partition(":")
    return (base, suffix) if sep else (base, None)


def _parse_pin_string(pin: str) -> tuple[str, int] | None:
    """Parse `"vX.Y:N"` (Pants-internal pin format) into `(version, revision)`.
    Returns `None` if the format is invalid."""
    parts = pin.split(":")
    if len(parts) != 2 or not parts[0]:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


def synthesize_pinned_buf_gen_yaml(
    content: bytes,
    source_path: str,
    *,
    extra_pins: Mapping[str, str] | None = None,
) -> bytes:
    """Return the user's `buf.gen.yaml` with `remote:` plugin pins resolved.

    For each `remote:` entry, the buf-recognized pinned form is:

        - remote: <id>:<version>
          revision: <int>
          out: ...

    Pants requires both fields. If a plugin entry is missing either, it must be
    in `DEFAULT_PLUGIN_PINS` (or the user's `extra_pins`) for Pants to fill in
    defaults. `extra_pins` values are `"vX.Y:N"` strings, parsed here.
    `protoc_builtin:` and `local:` plugins are not subject to pin enforcement.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if not isinstance(data, dict):
        return content
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return content

    parsed_extra: dict[str, tuple[str, int]] = {}
    for k, v in (extra_pins or {}).items():
        parsed = _parse_pin_string(v)
        if parsed is not None:
            parsed_extra[k] = parsed
    pins: Mapping[str, tuple[str, int]] = {**DEFAULT_PLUGIN_PINS, **parsed_extra}

    unresolvable: list[str] = []
    rewrote = False
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        val = plugin.get("remote")
        if val is None:
            continue
        ident = " ".join(str(x) for x in val) if isinstance(val, list) else str(val)
        base, version = _split_remote_ident(ident)
        revision = plugin.get("revision")
        if version is not None and isinstance(revision, int):
            continue  # already fully pinned
        default = pins.get(base)
        if default is None:
            unresolvable.append(ident)
            continue
        default_version, default_revision = default
        plugin["remote"] = f"{base}:{default_version}"
        plugin["revision"] = default_revision
        rewrote = True

    if unresolvable:
        bullets = "\n".join(f"  - remote: {ident}" for ident in unresolvable)
        known = ", ".join(sorted(DEFAULT_PLUGIN_PINS)) or "(none)"
        raise UnpinnedBufPluginError(
            f"`{source_path}` has `remote:` plugin entries that are missing a "
            f"version or `revision:`:\n{bullets}\n\n"
            "Pin both fields explicitly:\n\n"
            "    - remote: buf.build/owner/plugin:vX.Y\n"
            "      revision: N\n"
            "      out: ...\n\n"
            "Alternatively, for a plugin in Pants's built-in registry, leave both "
            "fields unset and Pants will fill in defaults. To extend the registry "
            "for your own plugins, use `[buf].extra_plugin_pins`.\n\n"
            f"Built-in registry: {known}."
        )

    if not rewrote:
        return content
    return yaml.safe_dump(data, sort_keys=False).encode("utf-8")


def check_pinned_remote_plugins(
    content: bytes,
    source_path: str,
    *,
    extra_pins: Mapping[str, str] | None = None,
) -> None:
    """Raise if `remote:` plugin entries can't be resolved to a full pin, without
    returning the synthesized content."""
    synthesize_pinned_buf_gen_yaml(content, source_path, extra_pins=extra_pins)


# ---- Per-target template request resolvers --------------------------------


def gen_template_request_from_fields(
    *,
    spec_path: str,
    address_str: str,
    override: str | None,
    buf: BufSubsystem,
) -> ConfigFilesRequest:
    """Resolve the `buf.gen.yaml` request from already-extracted field values.

    Precedence: per-target `buf_gen_template` (`override`) → `[buf].gen_template`
    subsystem option → `[buf].gen_template_discovery`.
    """
    if override is None:
        return buf.gen_template_request
    path = os.path.normpath(os.path.join(spec_path, override))
    return ConfigFilesRequest(
        specified=path,
        specified_option_name=f"`{BufGenTemplateField.alias}` field on {address_str}",
        discovery=False,
        check_existence=(path,),
    )


def gen_template_request_for_target(tgt: Target, buf: BufSubsystem) -> ConfigFilesRequest:
    """Convenience wrapper around `gen_template_request_from_fields` for a Target."""
    return gen_template_request_from_fields(
        spec_path=tgt.address.spec_path,
        address_str=str(tgt.address),
        override=tgt.get(BufGenTemplateField).value,
        buf=buf,
    )


def resolved_template_path(tgt: Target, buf: BufSubsystem) -> str | None:
    """Path to pass to `buf generate --template`, or None to rely on discovery."""
    override = tgt.get(BufGenTemplateField).value
    if override is not None:
        return os.path.normpath(os.path.join(tgt.address.spec_path, override))
    return buf.gen_template


# ---- Async fetchers + result types ----------------------------------------


@dataclass(frozen=True)
class BufLayout:
    """Module layout derived from `buf.yaml`."""

    buf_yaml_dir: str
    module_paths: tuple[str, ...]
    deps: tuple[str, ...]  # BSR module ids (e.g. `buf.build/bufbuild/protovalidate`)

    def root_for_proto(self, proto_path: str) -> str:
        return resolve_buf_module_root(proto_path, self.buf_yaml_dir, self.module_paths)


async def fetch_buf_layout(buf: BufSubsystem) -> BufLayout:
    """Read `buf.yaml` and return the parsed module layout. Empty if not found.

    `config_request` may also surface `buf.lock` (it's listed in `check_existence`
    so codegen invalidates on lock changes), so we filter to `buf.yaml` here.
    """
    files = await find_config_file(buf.config_request)
    yaml_paths = [p for p in files.snapshot.files if os.path.basename(p) == "buf.yaml"]
    if not yaml_paths:
        return BufLayout("", (), ())
    path = yaml_paths[0]
    contents = await get_digest_contents(files.snapshot.digest)
    content = next((dc.content for dc in contents if dc.path == path), b"")
    return BufLayout(
        os.path.dirname(path),
        parse_buf_yaml_module_paths(content),
        parse_buf_yaml_deps(content),
    )


@dataclass(frozen=True)
class BufGenContent:
    """Per-target `buf.gen.yaml` resolution.

    `template_path` is `None` when no template was found (callers should fall back
    to source-root path arithmetic). When set, `content` is the raw yaml.
    """

    target: Target
    template_path: str | None
    content: bytes


async def fetch_buf_gen_contents(
    targets: Sequence[Target], buf: BufSubsystem
) -> tuple[BufGenContent, ...]:
    """Resolve and read each target's effective `buf.gen.yaml`."""
    if not targets:
        return ()
    template_files_per_target = await concurrently(
        find_config_file(gen_template_request_for_target(t, buf)) for t in targets
    )
    contents_per_target = await concurrently(
        get_digest_contents(tf.snapshot.digest) for tf in template_files_per_target
    )
    out: list[BufGenContent] = []
    for tgt, files, dcs in zip(targets, template_files_per_target, contents_per_target):
        if not files.snapshot.files:
            out.append(BufGenContent(tgt, None, b""))
            continue
        path = files.snapshot.files[0]
        content = next((dc.content for dc in dcs if dc.path == path), b"")
        out.append(BufGenContent(tgt, path, content))
    return tuple(out)
