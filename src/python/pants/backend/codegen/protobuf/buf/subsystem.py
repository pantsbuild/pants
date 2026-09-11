# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    DictOption,
    FileOption,
    SkipOption,
)
from pants.util.strutil import softwrap


class BufSubsystem(TemplatedExternalTool):
    options_scope = "buf"
    name = "Buf"
    help = "A code generator, linter and formatter for Protocol Buffers (https://github.com/bufbuild/buf)."

    default_version = "v1.69.0"
    default_known_versions = [
        "v1.69.0|linux_arm64 |28b258cb4ee7a1224a61e1dd91ae5935f1c86c23e8e67bcfa23c8b096b0ad478|33862042",
        "v1.69.0|linux_x86_64|2b1f9cfb5e17d50c10dea9202979ffd28ca7ff7a6f4e51e801a9463986690b03|37497898",
        "v1.69.0|macos_arm64 |246534674239f326dd1ad2642e57865dd56dc4e98c4857d13da6eca4d3a168ad|35754114",
        "v1.69.0|macos_x86_64|570458723a1e400d654e916cc54a98e78a9c23d72775afde9ef12abcdebd37a1|38439569",
    ]
    default_url_template = (
        "https://github.com/bufbuild/buf/releases/download/{version}/buf-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "Darwin-arm64",
        "macos_x86_64": "Darwin-x86_64",
        "linux_arm64": "Linux-aarch64",
        "linux_x86_64": "Linux-x86_64",
    }

    format_skip = SkipOption("fmt", "lint")
    lint_skip = SkipOption("lint")
    format_args = ArgsListOption(example="--error-format json")
    lint_args = ArgsListOption(example="--error-format json")
    gen_args = ArgsListOption(example="--include-imports")

    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file understood by Buf
            (https://docs.buf.build/configuration/overview).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant root config files during runs
            (`buf.yaml`). If the json format is preferred, the path to the `buf.json`
            file should be provided in the config option.

            Use `[{cls.options_scope}].config` instead if your config is in a non-standard location.
            """
        ),
    )

    gen_template = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a `buf.gen.yaml` template used by `buf generate`
            (https://buf.build/docs/configuration/v2/buf-gen-yaml).

            Used when a `protobuf_source` target opts into buf-based code generation
            via the `protobuf_generator` field. May be overridden on a per-target
            basis via the `buf_gen_template` field.

            Setting this option will disable `[{cls.options_scope}].gen_template_discovery`. Use
            this option if the template is located in a non-standard location.
            """
        ),
    )
    gen_template_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant `buf.gen.yaml` files found at the
            repository root during code generation runs.

            Use `[{cls.options_scope}].gen_template` instead if your template is in a
            non-standard location, or use the `buf_gen_template` field for a per-target
            override.
            """
        ),
    )

    extra_plugin_pins = DictOption[str](
        default={},
        help=softwrap(
            """
            Map of `buf.gen.yaml` plugin ids to default `vX.Y:revN` pins that
            Pants will fill in for unpinned `remote:` entries, layered on top of
            Pants's built-in registry.

            Pants requires every `remote:` plugin to be pinned to an exact
            version+revision so codegen output is reproducible. For plugins in
            Pants's built-in registry, you can omit the pin and Pants synthesizes
            it. Use this option to do the same for custom or forked plugins, or
            to override the built-in default for a known plugin.

            Example:

                extra_plugin_pins = {
                  "myorg.example.com/internal/python-fork": "v2.0:3",
                }
            """
        ),
        advanced=True,
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://docs.buf.build/configuration/overview.
        # `buf.lock` is included so codegen / inference invalidate when BSR
        # `deps:` resolve to different module versions.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"{self.options_scope}.config",
            discovery=self.config_discovery,
            check_existence=("buf.yaml", "buf.lock"),
            check_content={},
        )

    @property
    def gen_template_request(self) -> ConfigFilesRequest:
        # Refer to https://buf.build/docs/configuration/v2/buf-gen-yaml.
        return ConfigFilesRequest(
            specified=self.gen_template,
            specified_option_name=f"{self.options_scope}.gen_template",
            discovery=self.gen_template_discovery,
            check_existence=("buf.gen.yaml",),
            check_content={},
        )

    def generate_exe(self, plat: Platform) -> str:
        return "./buf/bin/buf"
