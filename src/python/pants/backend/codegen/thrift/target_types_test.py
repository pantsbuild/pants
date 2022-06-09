# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

from pants.backend.codegen.thrift import target_types
from pants.backend.codegen.thrift.target_types import (
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.target import SingleSourceField, Tags
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_generate_source_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_types.rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        target_types=[ThriftSourcesGeneratorTarget],
    )
    rule_runner.write_files(
        {
            "src/thrift/BUILD": dedent(
                """\
                thrift_sources(
                    name='lib',
                    sources=['**/*.thrift'],
                    overrides={'f1.thrift': {'tags': ['overridden']}},
                )
                """
            ),
            "src/thrift/f1.thrift": "",
            "src/thrift/f2.thrift": "",
            "src/thrift/subdir/f.thrift": "",
        }
    )

    def gen_tgt(rel_fp: str, tags: list[str] | None = None) -> ThriftSourceTarget:
        return ThriftSourceTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address("src/thrift", target_name="lib", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join("src/thrift", rel_fp)),
        )

    generated = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("src/thrift", target_name="lib"), description_of_origin="tests"
            )
        ],
    ).parametrizations
    assert set(generated.values()) == {
        gen_tgt("f1.thrift", tags=["overridden"]),
        gen_tgt("f2.thrift"),
        gen_tgt("subdir/f.thrift"),
    }
