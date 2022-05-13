# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.docs.sphinx import sphinx_subsystem
from pants.backend.python.docs.sphinx.target_types import (
    SphinxSourcesGeneratorTarget,
    SphinxSourceTarget,
)
from pants.backend.python.docs.sphinx.target_types import rules as target_type_rules


def rules():
    return [*sphinx_subsystem.rules(), *target_type_rules()]


def target_types():
    return [SphinxSourceTarget, SphinxSourcesGeneratorTarget]
