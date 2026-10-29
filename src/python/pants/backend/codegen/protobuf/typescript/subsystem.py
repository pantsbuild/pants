# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.codegen.protobuf.buf.config import LanguageGenTemplate
from pants.option.option_types import FileOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class TypeScriptProtobufSubsystem(Subsystem):
    options_scope = "typescript-protobuf"
    help = "Options related to the Protobuf TypeScript backend."

    buf_gen_template = FileOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to the `buf.gen.yaml` template used to generate TypeScript. If unset,
            TypeScript uses `[buf].gen_template`, or a discovered `buf.gen.yaml`.

            Set this when other languages also generate with buf: one `buf generate` run
            executes every plugin in its template, and the TypeScript plugins need Node.js,
            which other languages' sandboxes don't have.

            Paths inside the template (`inputs:`, `out:`) are relative to the build root,
            because Pants runs `buf generate` from the sandbox root.
            """
        ),
    )

    buf_node_package_address = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Address of a `package_json` target whose `node_modules` provides npm plugins named
            in the TypeScript template (for example `plugins/typescript:typescript`). Only
            needed for npm plugins; `remote:`, `protoc_builtin:` and `[buf].codegen_plugins`
            plugins work without it.

            The package is installed into the sandbox and its `node_modules/.bin` is put on
            `PATH` for the `buf generate` process, so the template can name plugins without
            absolute paths. Its own sources are staged too, so a repo-local plugin can run.
            """
        ),
    )

    @property
    def language_gen_template(self) -> LanguageGenTemplate | None:
        return LanguageGenTemplate.from_option(self, "buf_gen_template")
