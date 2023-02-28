# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    generate_multiple_sources_field_help_message,
)

JS_FILE_EXTENSIONS = (".js", ".cjs", ".mjs")


class JSDependenciesField(Dependencies):
    pass


class JSSourceField(SingleSourceField):
    expected_file_extensions = JS_FILE_EXTENSIONS


class JSGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = JS_FILE_EXTENSIONS


# -----------------------------------------------------------------------------------------------
# `js_source` and `js_sources` targets
# -----------------------------------------------------------------------------------------------


class JSSourceTarget(Target):
    alias = "javascript_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSDependenciesField,
        JSSourceField,
    )
    help = "A single Javascript source file."


class JSSourcesGeneratorSourcesField(JSGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in JS_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.js', 'subdir/*.js', '!ignore_me.js']`"
    )


class JSSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "javascript_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSSourcesGeneratorSourcesField,
    )
    generated_target_cls = JSSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (JSDependenciesField,)
    help = "Generate a `javascript_source` target for each file in the `sources` field."
