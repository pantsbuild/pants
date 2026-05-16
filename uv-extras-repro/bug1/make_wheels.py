#!/usr/bin/env python3
"""
Generate fake wheels for the bug1 repro.

  requirements.in has TWO lines for pkg-a:
    pkg-a>=0.1.0              ← no extras
    pkg-a[x,y,z]              ← extras, no version constraint

  Pants emits both as separate req_strings. PEX satisfies pkg-a from the
  no-extras entry first, then treats pkg-a[x,y,z] as already resolved →
  pkg-c, pkg-d, pkg-e (only reachable via extras) are never added to the PEX.

  Fix: merge into a single line  pkg-a[x,y,z]>=0.1.0
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


# pkg-a: three extras, each activating a distinct leaf
make_wheel(
    "pkg-a", "0.1.0",
    [
        "Metadata-Version: 2.1",
        "Name: pkg-a",
        "Version: 0.1.0",
        "Provides-Extra: x",
        'Requires-Dist: pkg-c>=0.1.0; extra == "x"',
        "Provides-Extra: y",
        'Requires-Dist: pkg-d>=0.1.0; extra == "y"',
        "Provides-Extra: z",
        'Requires-Dist: pkg-e>=0.1.0; extra == "z"',
    ],
    {"pkg_a/__init__.py": '__version__ = "0.1.0"\n'},
)

# leaf packages — only reachable via pkg-a extras
for pkg in ["pkg-c", "pkg-d", "pkg-e"]:
    mod = pkg.replace("-", "_")
    make_wheel(
        pkg, "0.1.0",
        [
            "Metadata-Version: 2.1",
            f"Name: {pkg}",
            "Version: 0.1.0",
        ],
        {f"{mod}/__init__.py": '__version__ = "0.1.0"\n'},
    )

print("Done.")
