"""
Minimal repro for Pants 2.32 + uv resolver not activating transitive extras.

Dependency chain:
  google-cloud-speech==2.21.0  (direct dep in BUILD)
    -> google-api-core[grpc]  (in lockfile, no extras bracket → only optional-deps path)
       -> grpcio              (only in google-api-core.optional-dependencies.grpc)

Expected: grpcio is in the PEX because google-cloud-speech requires google-api-core[grpc].
Actual:   PEX assembly does not follow extra=[...] through optional-dependencies,
          so grpcio is absent and this import raises ImportError at runtime.
"""
import sys


def test_grpc_in_pex() -> None:
    import grpc  # type: ignore[import]

    # Make sure grpc is from the PEX, not some ambient env
    import importlib.util

    spec = importlib.util.find_spec("grpc")
    assert spec is not None, "grpc not found"
    grpc_path = spec.origin or ""
    # If running inside a PEX, the path will be inside .pex/
    print(f"grpc loaded from: {grpc_path}", file=sys.stderr)
    print(f"sys.path: {sys.path[:5]}", file=sys.stderr)
    assert grpc.__version__, "grpc.__version__ should be non-empty"
