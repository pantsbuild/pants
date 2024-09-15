# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.typescript.target_types import (
    TS_FILE_EXTENSIONS,
    TypeScriptDependenciesField,
    TypeScriptSourceField,
    TypeScriptTestSourceField,
)
from pants.core.goals.test import (
    TestExtraEnvVarsField,
    TestsBatchCompatibilityTagField,
    TestTimeoutField,
)
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    MultipleSourcesField,
    OverridesField,
    Target,
    TargetFilesGenerator,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text

TSX_FILE_EXTENSIONS = tuple(f"{ext}x" for ext in TS_FILE_EXTENSIONS)


class TSXDependenciesField(TypeScriptDependenciesField):
    pass


class TSXSourceField(TypeScriptSourceField):
    expected_file_extensions = TSX_FILE_EXTENSIONS


class TSXGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = TSX_FILE_EXTENSIONS


class TSXSourceTarget(Target):
    alias = "tsx_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSXDependenciesField,
        TSXSourceField,
    )
    help = "A single TSX source file."


class TSXSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        TSXSourceTarget.alias,
        """
        overrides={
            "foo.tsx": {"skip_prettier": True},
            "bar.tsx": {"skip_prettier": True},
            ("foo.tsx", "bar.tsx"): {"tags": ["no_lint"]},
        }
        """,
    )


class TSXSourcesGeneratorSourcesField(TSXGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in TSX_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.tsx', 'subdir/*.tsx', '!ignore_me.tsx']`"
    )


class TSXSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "tsx_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSXSourcesGeneratorSourcesField,
        TSXSourcesOverridesField,
    )
    generated_target_cls = TSXSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (TSXDependenciesField,)
    help = "Generate a `tsx_source` target for each file in the `sources` field."


class TSXTestDependenciesField(TSXDependenciesField):
    pass


class TSXTestSourceField(TSXSourceField, TypeScriptTestSourceField):
    expected_file_extensions = TSX_FILE_EXTENSIONS


class TSXTestTimeoutField(TestTimeoutField):
    pass


class TSXTestExtraEnvVarsField(TestExtraEnvVarsField):
    pass


class TSXTestBatchCompatibilityTagField(TestsBatchCompatibilityTagField):
    help = help_text(TestsBatchCompatibilityTagField.format_help("tsx_test", "nodejs test runner"))


class TSXTestTarget(Target):
    alias = "tsx_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSXTestDependenciesField,
        TSXTestSourceField,
        TSXTestTimeoutField,
        TSXTestExtraEnvVarsField,
        TSXTestBatchCompatibilityTagField,
    )
    help = "A single TSX test file."


class TSXTestsOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        TSXTestTarget.alias,
        """
        overrides={
            "foo.test.tsx": {"timeout": 120},
            "bar.test.tsx": {"timeout": 200},
            ("foo.test.tsx", "bar.test.tsx"): {"tags": ["slow_tests"]},
        }
        """,
    )


class TSXTestsGeneratorSourcesField(TSXGeneratorSourcesField):
    default = tuple(f"*.test{ext}" for ext in TSX_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.test.tsx', 'subdir/*.test.tsx', '!ignore_me.test.tsx']`"
    )


class TSXTestsGeneratorTarget(TargetFilesGenerator):
    alias = "tsx_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TSXTestsGeneratorSourcesField,
        TSXTestsOverridesField,
    )
    generated_target_cls = TSXTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        TSXTestDependenciesField,
        TSXTestTimeoutField,
        TSXTestExtraEnvVarsField,
        TSXTestBatchCompatibilityTagField,
    )
    help = "Generate a `tsx_test` target for each file in the `sources` field."
