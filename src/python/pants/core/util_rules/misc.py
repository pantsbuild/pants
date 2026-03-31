# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.engine.rules import collect_rules, rule
from pants.option.global_options import GlobalOptions, KeepSandboxes, NamedCachesDirOption
from pants.util.logging import LogLevel


@rule
async def log_level(global_options: GlobalOptions) -> LogLevel:
    return global_options.level


@rule
async def extract_keep_sandboxes(global_options: GlobalOptions) -> KeepSandboxes:
    return GlobalOptions.resolve_keep_sandboxes(global_options.options)


@rule
async def extract_named_caches_dir_option(global_options: GlobalOptions) -> NamedCachesDirOption:
    return NamedCachesDirOption(global_options.named_caches_dir)


def rules():
    return collect_rules()
