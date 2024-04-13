# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

from pants.backend.codegen.protobuf import target_types
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
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
        target_types=[ProtobufSourcesGeneratorTarget],
    )
    rule_runner.write_files(
        {
            "src/proto/BUILD": dedent(
                """\
                protobuf_sources(
                    name='lib',
                    sources=['**/*.proto'],
                    overrides={'f1.proto': {'tags': ['overridden']}},
                )
                """
            ),
            "src/proto/f1.proto": "",
            "src/proto/f2.proto": "",
            "src/proto/subdir/f.proto": "",
        }
    )

    def gen_tgt(rel_fp: str, tags: list[str] | None = None) -> ProtobufSourceTarget:
        return ProtobufSourceTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address("src/proto", target_name="lib", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join("src/proto", rel_fp)),
        )

    generated = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("src/proto", target_name="lib"), description_of_origin="tests"
            )
        ],
    ).parametrizations
    assert set(generated.values()) == {
        gen_tgt("f1.proto", tags=["overridden"]),
        gen_tgt("f2.proto"),
        gen_tgt("subdir/f.proto"),
    }
