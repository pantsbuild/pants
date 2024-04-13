# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

from pants.backend.codegen.soap import target_types
from pants.backend.codegen.soap.target_types import WsdlSourcesGeneratorTarget, WsdlSourceTarget
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
        target_types=[WsdlSourcesGeneratorTarget],
    )

    source_root = "src/wsdl"
    rule_runner.write_files(
        {
            f"{source_root}/BUILD": dedent(
                """\
                wsdl_sources(
                  name="lib",
                  sources=["**/*.wsdl"]
                )
                """
            ),
            f"{source_root}/f1.wsdl": "",
            f"{source_root}/sub/f2.wsdl": "",
        }
    )

    def gen_tgt(rel_fp: str, tags: list[str] | None = None) -> WsdlSourceTarget:
        return WsdlSourceTarget(
            {SingleSourceField.alias: rel_fp, Tags.alias: tags},
            Address(source_root, target_name="lib", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join(source_root, rel_fp)),
        )

    generated = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address(source_root, target_name="lib"), description_of_origin="tests"
            )
        ],
    ).parametrizations
    assert set(generated.values()) == {
        gen_tgt("f1.wsdl"),
        gen_tgt("sub/f2.wsdl"),
    }
