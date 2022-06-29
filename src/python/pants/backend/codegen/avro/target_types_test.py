# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

from pants.backend.codegen.avro import target_types
from pants.backend.codegen.avro.target_types import AvroSourcesGeneratorTarget, AvroSourceTarget
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
        target_types=[AvroSourcesGeneratorTarget],
    )
    rule_runner.write_files(
        {
            "src/avro/BUILD": dedent(
                """\
                avro_sources(
                    name='lib',
                    sources=['**/*.avsc', '**/*.avpr'],
                    overrides={'f1.avsc': {'tags': ['overridden']}},
                )
                """
            ),
            "src/avro/f1.avsc": "",
            "src/avro/f2.avpr": "",
            "src/avro/subdir/f.avsc": "",
        }
    )

    def gen_tgt(rel_fp: str, tags: list[str] | None = None) -> AvroSourceTarget:
        return AvroSourceTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address("src/avro", target_name="lib", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join("src/avro", rel_fp)),
        )

    generated = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("src/avro", target_name="lib"), description_of_origin="tests"
            )
        ],
    ).parametrizations
    assert set(generated.values()) == {
        gen_tgt("f1.avsc", tags=["overridden"]),
        gen_tgt("f2.avpr"),
        gen_tgt("subdir/f.avsc"),
    }
