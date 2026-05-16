#!/usr/bin/env python3
"""
Generate minimal fake wheels for the Pants + uv extras bug repro.

Chain under test:
  pkg-a (BUILD dep) → pkg-b (no extras)
                       └─ pkg-b → pkg-c[myextra]
                                   └─ pkg-c[myextra] → pkg-d (ONLY via extra)

If PEX/Pants drops the [myextra] specifier when following pkg-b's Requires-Dist,
pkg-d will be absent from requirements.pex and the test will fail with:
  Failed to resolve requirements ... pkg-d; extra == "myextra" ... had no 'pkg-d' distributions.
"""
import hashlib
import io
import zipfile
from pathlib import Path

OUT = Path(__file__).parent / "wheels"
OUT.mkdir(exist_ok=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_wheel(name: str, version: str, metadata_lines: list[str], modules: dict[str, str]) -> None:
    """Create a minimal valid wheel file."""
    dist_name = name.replace("-", "_")
    dist_info = f"{dist_name}-{version}.dist-info"
    whl_name = f"{dist_name}-{version}-py3-none-any.whl"

    metadata_body = "\n".join(metadata_lines) + "\n"
    wheel_body = "Wheel-Version: 1.0\nGenerator: make_wheels.py\nRoot-Is-Purelib: true\nTag: py3-none-any\n"

    files: dict[str, bytes] = {}
    for mod_path, mod_src in modules.items():
        files[mod_path] = mod_src.encode()
    files[f"{dist_info}/METADATA"] = metadata_body.encode()
    files[f"{dist_info}/WHEEL"] = wheel_body.encode()

    # RECORD: sha256=<hash>,<size> for each file; blank entry for RECORD itself
    record_lines = []
    for path, data in files.items():
        h = _sha256(data)
        record_lines.append(f"{path},sha256={h},{len(data)}")
    record_lines.append(f"{dist_info}/RECORD,,")
    record_body = "\n".join(record_lines) + "\n"
    files[f"{dist_info}/RECORD"] = record_body.encode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    (OUT / whl_name).write_bytes(buf.getvalue())
    print(f"wrote {whl_name}")


# pkg-a: plain package, depends on pkg-b (NO extras)
make_wheel(
    "pkg-a", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-a",
        "Version: 0.1.0",
        "Requires-Dist: pkg-b>=0.1.0",
    ],
    {"pkg_a/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-b: depends on pkg-c WITH [myextra] extras
make_wheel(
    "pkg-b", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-b",
        "Version: 0.1.0",
        "Requires-Dist: pkg-c[myextra]>=0.1.0",
    ],
    {"pkg_b/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-c: exposes pkg-d ONLY when [myextra] is activated
make_wheel(
    "pkg-c", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-c",
        "Version: 0.1.0",
        'Provides-Extra: myextra',
        'Requires-Dist: pkg-d>=0.1.0; extra == "myextra"',
    ],
    {"pkg_c/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-d: leaf package, only reachable via pkg-c[myextra]
make_wheel(
    "pkg-d", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-d",
        "Version: 0.1.0",
    ],
    {"pkg_d/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-e: SEPARATE direct dep that pulls in pkg-c WITHOUT extras.
# This simulates the m2 scenario where another package in req_strings also
# transitively depends on nflx-bdp-tracing but without the [grpc] extra.
# When PEX satisfies pkg-c from this path first (no extras), the [myextra]
# activation from pkg-b is skipped → pkg-d is never added.
make_wheel(
    "pkg-e", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-e",
        "Version: 0.1.0",
        "Requires-Dist: pkg-c>=0.1.0",
    ],
    {"pkg_e/__init__.py": '__version__ = "0.1.0"\n'},
)

print("Done.")
