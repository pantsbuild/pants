from pants.backend.nix.goals import run
from pants.backend.nix.target_types import NixBinaryTarget, NixSourceTarget


def target_types():
    return [NixBinaryTarget, NixSourceTarget]


def rules():
    return [*run.rules()]
