# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from textwrap import dedent  # noqa: PNT20
from typing import Dict, Iterable, Tuple


# Implements hashing algorithm from https://cs.opensource.google/go/x/mod/+/refs/tags/v0.5.0:sumdb/dirhash/hash.go.
def compute_module_hash(files: Iterable[Tuple[str, str]]) -> str:
    """Compute a module hash that can be used in go.sum for an emulated remote package."""
    sorted_files = sorted(files, key=lambda x: x[0])
    summary = ""
    for name, content in sorted_files:
        h = hashlib.sha256(content.encode())
        summary += f"{h.hexdigest()}  {name}\n"

    h = hashlib.sha256(summary.encode())
    summary_digest = base64.standard_b64encode(h.digest()).decode()
    return f"h1:{summary_digest}"


def gen_module_gomodproxy(
    version: str, import_path: str, files: Iterable[Tuple[str, str]]
) -> Dict[str, str | bytes]:
    go_mod_content = dedent(
        f"""\
        module {import_path}
        go 1.16
        """
    )

    go_mod_sum = compute_module_hash([("go.mod", go_mod_content)])
    prefix = f"{import_path}@{version}"

    all_files = [(f"{prefix}/go.mod", go_mod_content)]
    all_files.extend(((f"{prefix}/{path}", contents) for (path, contents) in files))

    mod_zip_bytes = io.BytesIO()
    with zipfile.ZipFile(mod_zip_bytes, "w") as mod_zip:
        for name, content in all_files:
            mod_zip.writestr(name, content)

    mod_zip_sum = compute_module_hash(all_files)

    return {
        "go.sum": dedent(
            f"""\
                {import_path} {version} {mod_zip_sum}
                {import_path} {version}/go.mod {go_mod_sum}
                """
        ),
        # Setup the third-party dependency as a custom Go module proxy site.
        # See https://go.dev/ref/mod#goproxy-protocol for details.
        f"go-mod-proxy/{import_path}/@v/list": f"{version}\n",
        f"go-mod-proxy/{import_path}/@v/{version}.info": json.dumps(
            {
                "Version": version,
                "Time": "2022-01-01T01:00:00Z",
            }
        ),
        f"go-mod-proxy/{import_path}/@v/{version}.mod": go_mod_content,
        f"go-mod-proxy/{import_path}/@v/{version}.zip": mod_zip_bytes.getvalue(),
    }
