"""
Repro: Pants 2.32 + uv resolver — extras-activated transitive dep missing from PEX.

Chain (all fake local wheels in bug2/wheels/):
  pkg-a==0.1.0   (direct dep in BUILD / req_strings)
    └─ pkg-b==0.1.0        (Requires-Dist of pkg-a, no extras at this edge)
         └─ pkg-c[myextra] (Requires-Dist of pkg-b, extras activated HERE)
              └─ pkg-d     (Requires-Dist of pkg-c, ONLY when extra == "myextra")

Key: pkg-d has NO non-extras path. If Pants drops the [myextra] specifier when
expanding the transitive closure from the uv lockfile into req_strings, or if
PEX fails to activate extras for pkg-c when it encounters pkg-b's Requires-Dist,
then pkg-d will be absent from requirements.pex.

Expected failure (bug present):
  Failed to resolve requirements from PEX environment @ requirements.pex.
  Needed ... pkg-d; extra == "myextra"
  Required by: pkg-c 0.1.0
  But this pex had no 'pkg-d' distributions.
"""
import sys


def test_pkg_d_reachable_via_transitive_extras() -> None:
    import pkg_d  # type: ignore[import]

    spec = __import__("importlib.util", fromlist=["util"]).find_spec("pkg_d")
    assert spec is not None, (
        "pkg_d not found — extras-activated transitive dep missing from PEX.\n"
        "Chain: pkg-a → pkg-b → pkg-c[myextra] → pkg-d\n"
        "PEX dropped [myextra] when building requirements.pex."
    )
    print(f"pkg_d loaded from: {spec.origin}", file=sys.stderr)
    assert pkg_d.__version__ == "0.1.0"
