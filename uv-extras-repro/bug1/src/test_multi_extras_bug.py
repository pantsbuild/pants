"""
Repro: Pants 2.32 + uv resolver — extras suppressed when the same package
appears twice in requirements.in: once without extras, once with.

  requirements.in:
    pkg-a>=0.1.0        ← no extras
    pkg-a[x,y,z]        ← extras, no version constraint

  pkg-a extras:
    [x] → pkg-c   (only via this extra)
    [y] → pkg-d   (only via this extra)
    [z] → pkg-e   (only via this extra)

Pants emits both lines as separate req_strings. PEX satisfies pkg-a from
the no-extras entry first, then treats pkg-a[x,y,z] as already resolved →
pkg-c, pkg-d, pkg-e are never added to the PEX.

Fix: merge into a single line:
  pkg-a[x,y,z]>=0.1.0

Expected failure (bug present):
  Failed to resolve requirements from PEX environment @ requirements.pex.
  Needed pkg-c>=0.1.0; extra == "x"
  Required by: pkg-a 0.1.0
  But this pex had no 'pkg-c' distributions.
"""
import sys


def test_all_extras_reachable() -> None:
    import pkg_c  # type: ignore[import]
    import pkg_d  # type: ignore[import]
    import pkg_e  # type: ignore[import]

    for name, mod in [("pkg-c", pkg_c), ("pkg-d", pkg_d), ("pkg-e", pkg_e)]:
        spec = __import__("importlib.util", fromlist=["util"]).find_spec(mod.__name__)
        assert spec is not None, (
            f"{name} not found — extras suppressed because pkg-a appears in "
            "requirements.in both with and without extras as separate lines."
        )
        print(f"{name} loaded from: {spec.origin}", file=sys.stderr)
        assert mod.__version__ == "0.1.0"
