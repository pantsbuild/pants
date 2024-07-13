# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.target_types import (
    JS_FILE_EXTENSIONS,
    JSRuntimeDependenciesField,
    JSRuntimeSourceField,
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

JSX_FILE_EXTENSIONS = tuple(f"{ext}x" for ext in JS_FILE_EXTENSIONS)


class JSXDependenciesField(JSRuntimeDependenciesField):
    pass


class JSXSourceField(JSRuntimeSourceField):
    expected_file_extensions = JSX_FILE_EXTENSIONS


class JSXGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = JSX_FILE_EXTENSIONS


class JSXSourceTarget(Target):
    alias = "jsx_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSXDependenciesField,
        JSXSourceField,
    )
    help = "A single JSX source file."


class JSXSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        JSXSourceTarget.alias,
        """
        overrides={
            "foo.jsx": {"skip_prettier": True},
            "bar.jsx": {"skip_prettier": True},
            ("foo.jsx", "bar.jsx"): {"tags": ["no_lint"]},
        }
        """,
    )


class JSXSourcesGeneratorSourcesField(JSXGeneratorSourcesField):
    default = tuple(f"*{ext}" for ext in JSX_FILE_EXTENSIONS)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.jsx', 'subdir/*.jsx', '!ignore_me.jsx']`"
    )


class JSXSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "jsx_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JSXSourcesGeneratorSourcesField,
        JSXSourcesOverridesField,
    )
    generated_target_cls = JSXSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (JSXDependenciesField,)
    help = "Generate a `jsx_source` target for each file in the `sources` field."
