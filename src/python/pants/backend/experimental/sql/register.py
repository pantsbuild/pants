from pants.backend.sql import tailor
from pants.backend.sql.target_types import SqlSourcesGeneratorTarget, SqlSourceTarget


def target_types():
    return [
        SqlSourceTarget,
        SqlSourcesGeneratorTarget,
    ]


def rules():
    return [*tailor.rules()]
