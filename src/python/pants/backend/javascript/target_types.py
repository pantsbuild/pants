# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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

JS_FILE_EXTENSIONS = (".js", ".cjs", ".mjs")
JS_TEST_FILE_EXTENSIONS = tuple(f"*.test{ext}" for ext in JS_FILE_EXTENSIONS)


class JSRuntimeDependenciesField(Dependencies):
    """Dependencies of a target that is javascript at runtime."""


class JSDependenciesField(JSRuntimeDependenciesField):
    pass


class JSRuntimeSourceField(SingleSourceField):
    """A source that is javascript at runtime."""


class JSSourceField(JSRuntimeSourceField):
    expected_file_extensions = JS_FILE_EXTENSIONS


class JSGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = JS_FILE_EXTENSIONS


class JSSourceTarget(Target):
    alias = "javascript_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSDependenciesField,
        JSSourceField,
    )
    help = "A single Javascript source file."


class JSSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        JSSourceTarget.alias,
        """
        overrides={
            "foo.js": {"skip_prettier": True},
            "bar.js": {"skip_prettier": True},
            ("foo.js", "bar.js"): {"tags": ["no_lint"]},
        }
        """,
    )


class JSSourcesGeneratorSourcesField(JSGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in JS_FILE_EXTENSIONS) + tuple(
        f"!{pat}" for pat in JS_TEST_FILE_EXTENSIONS
    )
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.js', 'subdir/*.js', '!ignore_me.js']`"
    )


class JSSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "javascript_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSSourcesGeneratorSourcesField,
        JSSourcesOverridesField,
    )
    generated_target_cls = JSSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (JSDependenciesField,)
    help = "Generate a `javascript_source` target for each file in the `sources` field."


class JSTestDependenciesField(JSDependenciesField):
    pass


class JSTestSourceField(JSSourceField):
    expected_file_extensions = JS_FILE_EXTENSIONS


class JSTestTimeoutField(TestTimeoutField):
    pass


class JSTestExtraEnvVarsField(TestExtraEnvVarsField):
    pass


class JSTestBatchCompatibilityTagField(TestsBatchCompatibilityTagField):
    help = help_text(
        TestsBatchCompatibilityTagField.format_help("javascript_test", "nodejs test runner")
    )


class JSTestTarget(Target):
    alias = "javascript_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSTestDependenciesField,
        JSTestSourceField,
        JSTestTimeoutField,
        JSTestExtraEnvVarsField,
        JSTestBatchCompatibilityTagField,
    )
    help = "A single Javascript test file."


class JSTestsOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        JSTestTarget.alias,
        """
        overrides={
            "foo.test.js": {"timeout": 120},
            "bar.test.js": {"timeout": 200},
            ("foo.test.js", "bar.test.js"): {"tags": ["slow_tests"]},
        }
        """,
    )


class JSTestsGeneratorSourcesField(JSGeneratorSourcesField):
    default = tuple(f"*.test{ext}" for ext in JS_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.test.js', 'subdir/*.test.mjs', '!ignore_me.test.js']`"
    )


class JSTestsGeneratorTarget(TargetFilesGenerator):
    alias = "javascript_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSTestsGeneratorSourcesField,
        JSTestsOverridesField,
    )
    generated_target_cls = JSTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        JSTestDependenciesField,
        JSTestTimeoutField,
        JSTestExtraEnvVarsField,
        JSTestBatchCompatibilityTagField,
    )
    help = "Generate a `javascript_test` target for each file in the `sources` field."
