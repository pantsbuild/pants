# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()


_DEFAULT_RULES = (
    # Allow dependencies within/between backends.
    "/**",
    # Allow the pants bin plugins target to depend on backends.
    # BUG: can't use the actual target address here..
    # "src/python/pants/bin:plugins", <-- broken
    "src/python/pants/bin",
    # Allow test utils and fixtures to depend on code in backend modules.
    "/../testutil/**",
    "//pants-plugins/internal_plugins/test_lockfile_fixtures/*",
    # Allow test sources to depend on code in backend modules.
    # Would prefer to filter on target type here, rather than on file name..
    # This relates to this issue comment:
    # https://github.com/pantsbuild/pants/issues/17873#issuecomment-1364153426
    # So we could instead say: "*_tests" and that would match all target types that end with `_tests`.
    "*_test.py",
    "//tests/**",
    # Allow build-support to use what ever.
    "//build-support/**",
    # Deny all others.
    "!*",
)


__dependents_rules__(
    # Exceptional rule sets:
    (
        (
            "[/build_files/fix/deprecations/base.py]",
            "[/build_files/fix/deprecations/renamed_fields_rules.py]",
            "[/build_files/fix/deprecations/renamed_targets_rules.py]",
            "[/build_files/fmt/black/register.py]",
            "[/build_files/fmt/yapf/register.py]",
            "[/python/lint/black/rules.py]",
            "[/python/lint/black/subsystem.py]",
            "[/python/lint/yapf/rules.py]",
            "[/python/lint/yapf/subsystem.py]",
        ),
        "src/python/pants/core/goals/update_build_files.py",
        _DEFAULT_RULES,
    ),
    (
        (
            "[/python/util_rules/interpreter_constraints.py]",
            "[/python/util_rules/pex_environment.py]",
            "[/python/util_rules/pex_requirements.py]",
        ),
        "src/python/pants/init/plugin_resolver.py",
        _DEFAULT_RULES,
    ),
    (
        # This section is sub-optimal. It would be easier to reason about if rules from sets with
        # identical selectors where merged. i.e. If we could include the
        # `[/python/util_rules/pex.py]` selector in each of the two previous rule sets, we could get
        # rid of this one entirely.
        "[/python/util_rules/pex.py]",
        "src/python/pants/core/goals/update_build_files.py",
        "src/python/pants/init/plugin_resolver.py",
        _DEFAULT_RULES,
    ),
    (
        "[/python/goals/setup_py.py]",
        "//pants-plugins/internal_plugins/releases/register.py",
        _DEFAULT_RULES,
    ),
    (
        "[/project_info/filter_targets.py]",
        "src/python/pants/build_graph/build_configuration.py",
        "src/python/pants/engine/internals/specs_rules.py",
        "src/python/pants/engine/internals/mapper.py",
        _DEFAULT_RULES,
    ),
    (
        "[/project_info/dependents.py]",
        "src/python/pants/vcs/changed.py",
        _DEFAULT_RULES,
    ),
    (
        "[/project_info/peek.py]",
        "src/python/pants/explorer/server/graphql/**",
        _DEFAULT_RULES,
    ),
    (
        "[/project_info]",
        "src/python/pants/init/extension_loader.py",
        _DEFAULT_RULES,
    ),
    (
        "[/java/subsystems/java_infer.py]",
        "src/python/pants/jvm/dependency_inference/artifact_mapper.py",
        _DEFAULT_RULES,
    ),
    (
        "[/java/subsystems/junit.py]",
        "src/python/pants/jvm/test/junit.py",
        _DEFAULT_RULES,
    ),
    (
        "[/docker/target_types.py]",
        "src/python/pants/explorer/server/graphql/query/conftest.py",
        _DEFAULT_RULES,
    ),
    (
        "[/codegen/export_codegen_goal.py]",
        "src/python/pants/core/register.py",
        _DEFAULT_RULES,
    ),
    (
        "[/__init__.py]",
        "src/python/pants/help/help_info_extracter.py",
        _DEFAULT_RULES,
    ),
    # Generic rule set:
    (
        # Applies to all targets in this subtree.
        "*",
        _DEFAULT_RULES,
    ),
)
