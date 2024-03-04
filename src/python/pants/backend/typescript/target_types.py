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
TS_TEST_FILE_EXTENSIONS = tuple(f"*.test{ext}" for ext in TS_FILE_EXTENSIONS)


class TypeScriptDependenciesField(Dependencies):
    pass


class TypeScriptSourceField(SingleSourceField):
    expected_file_extensions = TS_FILE_EXTENSIONS


class TypeScriptGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = TS_FILE_EXTENSIONS


class TypeScriptSourceTarget(Target):
    alias = "typescript_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TypeScriptDependenciesField,
        TypeScriptSourceField,
    )
    help = "A single TypeScript source file."


class TypeScriptSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        generated_target_name=TypeScriptSourceTarget.alias,
        example="""
        overrides={
            "foo.ts": {"skip_prettier": True},
            "bar.ts": {"skip_prettier": True},
            ("foo.ts", "bar.ts"): {"tags": ["no_lint"]},
        }
        """,
    )


class TypeScriptSourcesGeneratorSourcesField(TypeScriptGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in TS_FILE_EXTENSIONS) + tuple(
        f"!{pat}" for pat in TS_TEST_FILE_EXTENSIONS
    )
    help = generate_multiple_sources_field_help_message(
        files_example="Example: `sources=['utils.ts', 'subdir/*.ts', '!ignore_me.ts']`"
    )


class TypeScriptSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "typescript_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TypeScriptSourcesGeneratorSourcesField,
        TypeScriptSourcesOverridesField,
    )
    generated_target_cls = TypeScriptSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (TypeScriptDependenciesField,)
    help = "Generate a `typescript_source` target for each file in the `sources` field."


class TypeScriptTestDependenciesField(TypeScriptDependenciesField):
    pass


class TypeScriptTestSourceField(TypeScriptSourceField):
    expected_file_extensions = TS_FILE_EXTENSIONS


class TypeScriptTestTimeoutField(TestTimeoutField):
    pass


class TypeScriptTestExtraEnvVarsField(TestExtraEnvVarsField):
    pass


class TypeScriptTestBatchCompatibilityTagField(TestsBatchCompatibilityTagField):
    help = help_text(
        TestsBatchCompatibilityTagField.format_help("typescript_test", "nodejs test runner")
    )


class TypeScriptTestTarget(Target):
    alias = "typescript_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TypeScriptTestDependenciesField,
        TypeScriptTestSourceField,
        TypeScriptTestTimeoutField,
        TypeScriptTestExtraEnvVarsField,
        TypeScriptTestBatchCompatibilityTagField,
    )
    help = "A single TypeScript test file."


class TypeScriptTestsOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        generated_target_name=TypeScriptTestTarget.alias,
        example="""
        overrides={
            "foo.test.ts": {"timeout": 120},
            "bar.test.ts": {"timeout": 200},
            ("foo.test.ts", "bar.test.ts"): {"tags": ["slow_tests"]},
        }
        """,
    )


class TypeScriptTestsGeneratorSourcesField(TypeScriptGeneratorSourcesField):
    default = TS_TEST_FILE_EXTENSIONS
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.test.ts', 'subdir/*.test.ts', '!ignore_me.test.ts']`"
    )


class TypeScriptTestsGeneratorTarget(TargetFilesGenerator):
    alias = "typescript_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TypeScriptTestsGeneratorSourcesField,
        TypeScriptTestsOverridesField,
    )
    generated_target_cls = TypeScriptTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        TypeScriptTestDependenciesField,
        TypeScriptTestTimeoutField,
        TypeScriptTestExtraEnvVarsField,
        TypeScriptTestBatchCompatibilityTagField,
    )
    help = "Generate a `typescript_test` target for each file in the `sources` field."
