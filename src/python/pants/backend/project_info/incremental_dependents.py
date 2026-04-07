# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Incremental dependency graph updates for faster `--changed-dependents` runs.

Instead of resolving dependencies for ALL targets every time, this module persists
the forward dependency graph to disk and only re-resolves dependencies for targets
whose source files have changed since the last run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from pants.base.build_environment import get_pants_cachedir
from pants.engine.addresses import Address
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import help_text

logger = logging.getLogger(__name__)


class IncrementalDependents(Subsystem):
    options_scope = "incremental-dependents"
    help = help_text(
        """
        Persist the forward dependency graph to disk and incrementally update it,
        so that `--changed-dependents=transitive` does not need to resolve
        dependencies for every target on every run.
        """
    )

    enabled = BoolOption(
        default=False,
        help="Enable incremental dependency graph caching. "
        "When enabled, the forward dependency graph is persisted to disk and only "
        "targets with changed source files have their dependencies re-resolved.",
    )


# ---------------------------------------------------------------------------
# Address serialization
# ---------------------------------------------------------------------------


def address_to_json(addr: Address) -> list[Any]:
    """Serialize an Address to a JSON-friendly list.

    Format: [spec_path, target_name, generated_name_or_null, {params} or null]
    """
    params = dict(addr.parameters) if addr.parameters else None
    return [addr.spec_path, addr.target_name, addr.generated_name, params]


def address_from_json(data: list[Any]) -> Address:
    """Reconstruct an Address from its JSON representation."""
    spec_path, target_name, generated_name, params = data
    return Address(
        spec_path,
        target_name=target_name,
        generated_name=generated_name,
        parameters=params if params else None,
    )


# ---------------------------------------------------------------------------
# Persisted graph helpers
# ---------------------------------------------------------------------------

_CACHE_VERSION = 2  # v2: stores structured address components


@dataclass(frozen=True)
class CachedEntry:
    fingerprint: str
    # Each dep is stored as a list: [spec_path, target_name, generated_name, params]
    deps_json: tuple[tuple[Any, ...], ...]


def get_cache_path() -> str:
    """Return the path to the incremental dep graph cache file."""
    return os.path.join(get_pants_cachedir(), "incremental_dep_graph_v2.json")


def load_persisted_graph(path: str, buildroot: str) -> dict[str, CachedEntry]:
    """Load the persisted forward dependency graph from disk.

    Returns an empty dict if the file doesn't exist or is invalid.
    """
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("version") != _CACHE_VERSION:
            logger.debug("Incremental dep graph cache version mismatch, rebuilding.")
            return {}
        if data.get("buildroot") != buildroot:
            logger.debug("Incremental dep graph cache buildroot mismatch, rebuilding.")
            return {}
        entries: dict[str, CachedEntry] = {}
        for addr_spec, entry in data.get("entries", {}).items():
            entries[addr_spec] = CachedEntry(
                fingerprint=entry["fingerprint"],
                deps=tuple(entry["deps"]),
            )
        return entries
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug("Could not load incremental dep graph cache: %s", e)
        return {}


def save_persisted_graph(
    path: str,
    buildroot: str,
    entries: dict[str, CachedEntry],
) -> None:
    """Save the forward dependency graph to disk."""
    data = {
        "version": _CACHE_VERSION,
        "buildroot": buildroot,
        "entries": {
            addr_spec: {
                "fingerprint": entry.fingerprint,
                "deps": list(entry.deps),
            }
            for addr_spec, entry in entries.items()
        },
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Atomic write: write to temp file then rename
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp_path, path)
        logger.debug("Saved incremental dep graph cache with %d entries to %s", len(entries), path)
    except OSError as e:
        logger.warning("Failed to save incremental dep graph cache: %s", e)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def compute_source_fingerprint(target_address: Address, buildroot: str) -> str:
    """Compute a fast fingerprint for a target based on its source files' mtime+size.

    We use the target's spec_path (directory) and the BUILD file as the primary
    signal. For file-level targets (generated targets with a file name), we also
    include that specific file's mtime+size.

    This is a fast proxy that avoids hydrating sources through the Pants engine.
    The fingerprint changes whenever:
    - The BUILD file defining the target changes
    - The specific source file (for generated targets) changes
    """
    hasher = hashlib.sha256()

    # Always include the BUILD file(s) in the fingerprint
    spec_path = target_address.spec_path
    build_dir = os.path.join(buildroot, spec_path) if spec_path else buildroot

    for build_name in ("BUILD", "BUILD.pants"):
        build_file = os.path.join(build_dir, build_name)
        try:
            st = os.stat(build_file)
            hasher.update(f"BUILD:{build_file}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass

    # For file-addressed targets (e.g. python_source generated from python_sources),
    # include the file's own mtime+size.
    if target_address.is_generated_target and target_address.generated_name:
        gen_name = target_address.generated_name
        candidate = (
            os.path.join(buildroot, spec_path, gen_name)
            if spec_path
            else os.path.join(buildroot, gen_name)
        )
        try:
            st = os.stat(candidate)
            hasher.update(f"SRC:{candidate}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            # Also try as a path directly from buildroot
            candidate2 = os.path.join(buildroot, gen_name)
            if candidate2 != candidate:
                try:
                    st = os.stat(candidate2)
                    hasher.update(f"SRC:{candidate2}:{st.st_mtime_ns}:{st.st_size}".encode())
                except OSError:
                    pass

    return hasher.hexdigest()
