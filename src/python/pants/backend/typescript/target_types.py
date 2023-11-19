# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.core.goals.test import (
    TestExtraEnvVarsField,
    TestsBatchCompatibilityTagField,
    TestTimeoutField,
)
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text

TS_FILE_EXTENSIONS = (".ts", ".tsx")


class TSDependenciesField(Dependencies):
    pass


class TSSourceField(SingleSourceField):
    expected_file_extensions = TS_FILE_EXTENSIONS


class TSGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = TS_FILE_EXTENSIONS


class TSSourceTarget(Target):
    alias = "typescript_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSDependenciesField,
        TSSourceField,
    )
    help = "A single TypeScript source file."


class TSSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        generated_target_name=TSSourceTarget.alias,
        example="""
        overrides={
            "foo.ts": {"skip_prettier": True},
            "bar.ts": {"skip_prettier": True},
            ("foo.ts", "bar.ts"): {"tags": ["no_lint"]},
        }
        """,
    )


class TSSourcesGeneratorSourcesField(TSGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in TS_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        files_example="Example: `sources=['utils.ts', 'subdir/*.ts', '!ignore_me.ts']`"
    )


class TSSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "typescript_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSSourcesGeneratorSourcesField,
        TSSourcesOverridesField,
    )
    generated_target_cls = TSSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (TSDependenciesField,)
    help = "Generate a `typescript_source` target for each file in the `sources` field."


class TSTestDependenciesField(TSDependenciesField):
    pass


class TSTestSourceField(TSSourceField):
    expected_file_extensions = TS_FILE_EXTENSIONS


class TSTestTimeoutField(TestTimeoutField):
    pass


class TSTestExtraEnvVarsField(TestExtraEnvVarsField):
    pass


class TSTestBatchCompatibilityTagField(TestsBatchCompatibilityTagField):
    help = help_text(
        TestsBatchCompatibilityTagField.format_help("typescript_test", "nodejs test runner")
    )


class TSTestTarget(Target):
    alias = "typescript_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSTestDependenciesField,
        TSTestSourceField,
        TSTestTimeoutField,
        TSTestExtraEnvVarsField,
        TSTestBatchCompatibilityTagField,
    )
    help = "A single TypeScript test file."


class TSTestsOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        generated_target_name=TSTestTarget.alias,
        example="""
        overrides={
            "foo.test.ts": {"timeout": 120},
            "bar.test.ts": {"timeout": 200},
            ("foo.test.ts", "bar.test.ts"): {"tags": ["slow_tests"]},
        }
        """,
    )


class TSTestsGeneratorSourcesField(TSGeneratorSourcesField):
    default = tuple(f"*.test{ext}" for ext in TS_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.test.ts', 'subdir/*.test.ts', '!ignore_me.test.ts']`"
    )


class TSTestsGeneratorTarget(TargetFilesGenerator):
    alias = "typescript_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSTestsGeneratorSourcesField,
        TSTestsOverridesField,
    )
    generated_target_cls = TSTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        TSTestDependenciesField,
        TSTestTimeoutField,
        TSTestExtraEnvVarsField,
        TSTestBatchCompatibilityTagField,
    )
    help = "Generate a `typescript_test` target for each file in the `sources` field."
