"""
Repro: Pants 2.32 + uv resolver — extras-activated transitive dep missing from PEX
when a competing req_string satisfies the same package without extras first.

Chain (all fake local wheels in bug2/wheels/):
  pkg-f==0.1.0   (req_string)
    └─ pkg-g      (no extras at this edge)
         └─ pkg-h[myextra]   (extras activated HERE, 2nd level from req_string)
              └─ pkg-i        (ONLY via extra, no other path)

  pkg-j==0.1.0   (req_string)
    └─ pkg-h      (no extras — competing path to pkg-h)

When PEX processes pkg-j first, pkg-h is added without extras.
The extras path via pkg-g → pkg-h[myextra] is then skipped →
pkg-i is never added to the PEX.

Expected failure (bug present):
  Failed to resolve requirements from PEX environment @ requirements.pex.
  Needed pkg-i>=0.1.0; extra == "myextra"
  Required by: pkg-h 0.1.0
  But this pex had no 'pkg-i' distributions.
"""
import sys


def test_pkg_i_reachable_via_transitive_extras() -> None:
    import pkg_i  # type: ignore[import]

    spec = __import__("importlib.util", fromlist=["util"]).find_spec("pkg_i")
    assert spec is not None, (
        "pkg_i not found — extras-activated transitive dep missing from PEX.\n"
        "Chain: pkg-f → pkg-g → pkg-h[myextra] → pkg-i\n"
        "Competing path pkg-j → pkg-h (no extras) caused pkg-h to be satisfied "
        "without extras, so [myextra] was never activated."
    )
    print(f"pkg_i loaded from: {spec.origin}", file=sys.stderr)
    assert pkg_i.__version__ == "0.1.0"
