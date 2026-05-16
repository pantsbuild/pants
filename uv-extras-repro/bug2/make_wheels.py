#!/usr/bin/env python3
"""
Generate fake wheels for the bug2 repro.

Chain under test:
  pkg-f (BUILD dep) → pkg-g (no extras)
                       └─ pkg-g → pkg-h[myextra]
                                   └─ pkg-h[myextra] → pkg-i (ONLY via extra)

  pkg-j → pkg-h (no extras) ← competing path; also a BUILD dep

If PEX satisfies pkg-h from pkg-j first (without extras), the [myextra]
activation from pkg-g is skipped → pkg-i is never added to the PEX.
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

    record_lines = []
    for path, data in files.items():
        h = _sha256(data)
        record_lines.append(f"{path},sha256={h},{len(data)}")
    record_lines.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(record_lines) + "\n").encode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    (OUT / whl_name).write_bytes(buf.getvalue())
    print(f"wrote {whl_name}")


# pkg-f: BUILD dep, depends on pkg-g (no extras)
make_wheel(
    "pkg-f", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-f",
        "Version: 0.1.0",
        "Requires-Dist: pkg-g>=0.1.0",
    ],
    {"pkg_f/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-g: depends on pkg-h WITH [myextra]
make_wheel(
    "pkg-g", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-g",
        "Version: 0.1.0",
        "Requires-Dist: pkg-h[myextra]>=0.1.0",
    ],
    {"pkg_g/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-h: exposes pkg-i ONLY when [myextra] is activated
make_wheel(
    "pkg-h", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-h",
        "Version: 0.1.0",
        "Provides-Extra: myextra",
        'Requires-Dist: pkg-i>=0.1.0; extra == "myextra"',
    ],
    {"pkg_h/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-i: leaf, only reachable via pkg-h[myextra]
make_wheel(
    "pkg-i", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-i",
        "Version: 0.1.0",
    ],
    {"pkg_i/__init__.py": '__version__ = "0.1.0"\n'},
)

# pkg-j: BUILD dep, depends on pkg-h WITHOUT extras (competing path)
make_wheel(
    "pkg-j", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-j",
        "Version: 0.1.0",
        "Requires-Dist: pkg-h>=0.1.0",
    ],
    {"pkg_j/__init__.py": '__version__ = "0.1.0"\n'},
)

print("Done.")
