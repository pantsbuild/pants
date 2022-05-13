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
)

JS_FILE_EXTENSIONS = (".js",)


class JSSourceField(SingleSourceField):
    expected_file_extensions = JS_FILE_EXTENSIONS


class JSGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = JS_FILE_EXTENSIONS


# -----------------------------------------------------------------------------------------------
# `js_source` and `js_sources` targets
# -----------------------------------------------------------------------------------------------


class JSSourceTarget(Target):
    alias = "js_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JSSourceField,
    )
    help = "A single Javascript source file."


class JSSourcesGeneratorSourcesField(JSGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in JS_FILE_EXTENSIONS)


class JSSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "js_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSSourcesGeneratorSourcesField,
    )
    generated_target_cls = JSSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (Dependencies,)
    help = "Generate a `js_source` target for each file in the `sources` field."


# def rules():
#     return collect_rules()
