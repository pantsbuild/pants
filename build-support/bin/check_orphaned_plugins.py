#!/usr/bin/env python
# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import subprocess

NOT_DISTRIBUTED_BACKENDS = {
    "internal_plugins.releases",
    "internal_plugins.test_lockfile_fixtures",
    "pants_explorer.server",
}


def main() -> None:
    discovered_backends = get_backends()
    distributed_backends = get_pants_binary_plugins()
    orphaned_backends = discovered_backends - distributed_backends
    if orphaned_backends:
        print(
            f"These are discovered backends, which are not included in the pantsbuild.pants distribution:\n  * "
            + "\n  * ".join(
                f"  ({be} - intentionally excluded)" if be in NOT_DISTRIBUTED_BACKENDS else be
                for be in sorted(orphaned_backends)
            )
        )


def get_pants_binary_plugins() -> set[str]:
    return {
        plugin_path_to_backend(plugin)
        for plugin in run_pants("peek", "src/python/pants/bin:plugins")[0]["dependencies_raw"]
    }


def plugin_path_to_backend(plugin: str) -> str:
    return plugin.replace("src/python/", "").replace("/", ".")


def get_backends() -> set[str]:
    return set(get_help_info()["name_to_backend_help_info"])


def get_help_info() -> dict:
    return run_pants("help-all")


def run_pants(*args: str) -> dict:
    return json.loads(
        subprocess.run(
            ["pants", *args],
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.decode()
    )


if __name__ == "__main__":
    main()
