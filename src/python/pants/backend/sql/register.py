from pants.engine.target import TargetFilesGeneratorSettingsRequest
from pants.engine.unions import UnionRule

from . import tailor
from .target_types import SqlSourcesGeneratorTarget, SqlSourceTarget


def target_types():
    return [
        SqlSourceTarget,
        SqlSourcesGeneratorTarget,
    ]


def rules():
    return [*tailor.rules()]
