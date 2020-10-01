# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.core.target_types import (
    Files,
    FilesSources,
    RelocatedFiles,
    RelocateFilesViaCodegenRequest,
)
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.target import GeneratedSources, Sources, TransitiveTargets
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_relocated_files() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_type_rules(),
            *source_files_rules(),
            QueryRule(GeneratedSources, [RelocateFilesViaCodegenRequest]),
            QueryRule(TransitiveTargets, [Addresses]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[Files, RelocatedFiles],
    )

    def assert_prefix_mapping(
        *,
        original: str,
        src: str,
        dest: str,
        expected: str,
    ) -> None:
        rule_runner.create_file(original)
        rule_runner.add_to_build_file(
            "",
            dedent(
                f"""\
                files(name="original", sources=[{repr(original)}])

                relocated_files(
                    name="relocated",
                    files_targets=[":original"],
                    src={repr(src)},
                    dest={repr(dest)},
                )
                """
            ),
            overwrite=True,
        )
        tgt = rule_runner.get_target(Address("", target_name="relocated"))
        result = rule_runner.request(
            GeneratedSources, [RelocateFilesViaCodegenRequest(EMPTY_SNAPSHOT, tgt)]
        )
        assert result.snapshot.files == (expected,)

        # We also ensure that when looking at the transitive dependencies of the `relocated_files`
        # target and then getting all the code of that closure, we only end up with the relocated
        # files. If we naively marked the original files targets as a typical `Dependencies` field,
        # we would hit this issue.
        transitive_targets = rule_runner.request(TransitiveTargets, [Addresses([tgt.address])])
        all_sources = rule_runner.request(
            SourceFiles,
            [
                SourceFilesRequest(
                    (tgt.get(Sources) for tgt in transitive_targets.closure),
                    enable_codegen=True,
                    for_sources_types=(FilesSources,),
                )
            ],
        )
        assert all_sources.snapshot.files == (expected,)

    # No-op.
    assert_prefix_mapping(original="old_prefix/f.ext", src="", dest="", expected="old_prefix/f.ext")
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="old_prefix",
        dest="old_prefix",
        expected="old_prefix/f.ext",
    )

    # Remove prefix.
    assert_prefix_mapping(original="old_prefix/f.ext", src="old_prefix", dest="", expected="f.ext")
    assert_prefix_mapping(
        original="old_prefix/subdir/f.ext", src="old_prefix", dest="", expected="subdir/f.ext"
    )

    # Add prefix.
    assert_prefix_mapping(original="f.ext", src="", dest="new_prefix", expected="new_prefix/f.ext")
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="",
        dest="new_prefix",
        expected="new_prefix/old_prefix/f.ext",
    )

    # Replace prefix.
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="old_prefix",
        dest="new_prefix",
        expected="new_prefix/f.ext",
    )
    assert_prefix_mapping(
        original="old_prefix/f.ext",
        src="old_prefix",
        dest="new_prefix/subdir",
        expected="new_prefix/subdir/f.ext",
    )

    # Replace prefix, but preserve a common start.
    assert_prefix_mapping(
        original="common_prefix/foo/f.ext",
        src="common_prefix/foo",
        dest="common_prefix/bar",
        expected="common_prefix/bar/f.ext",
    )
    assert_prefix_mapping(
        original="common_prefix/subdir/f.ext",
        src="common_prefix/subdir",
        dest="common_prefix",
        expected="common_prefix/f.ext",
    )
