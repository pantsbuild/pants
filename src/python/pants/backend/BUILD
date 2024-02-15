# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()


# Setup rules about which parts of the codebase may depend on backend sources.

DEFAULT_DEPENDENTS_RULES = (
    # Allow dependencies within/between backends.
    "/**",
    # Allow the pants bin plugins target to depend on backends.
    "src/python/pants/bin:plugins",
    # Allow test utils and fixtures to depend on code in backend modules.
    "/../testutil/**",
    "//pants-plugins/internal_plugins/test_lockfile_fixtures/*",
    # Allow test sources to depend on code in backend modules.
    "<*_tests>",
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
            "[/build_files/fmt/ruff/register.py]",
            "[/build_files/fmt/yapf/register.py]",
            "[/python/lint/black/rules.py]",
            "[/python/lint/black/subsystem.py]",
            "[/python/lint/ruff/fmt_rules.py]",
            "[/python/lint/ruff/check_rules.py]",
            "[/python/lint/ruff/subsystem.py]",
            "[/python/lint/yapf/rules.py]",
            "[/python/lint/yapf/subsystem.py]",
            "[src/python/pants/backend/python/goals/lockfile.py]",
            "[src/python/pants/backend/python/subsystems/python_tool_base.py]",
        ),
        "src/python/pants/core/goals/update_build_files.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        (
            "[/python/util_rules/interpreter_constraints.py]",
            "[/python/util_rules/pex_environment.py]",
            "[/python/util_rules/pex_requirements.py]",
        ),
        "src/python/pants/init/plugin_resolver.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/python/util_rules/pex.py]",
        "src/python/pants/core/goals/update_build_files.py",
        "src/python/pants/init/plugin_resolver.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/python/util_rules/package_dists.py]",
        "//pants-plugins/internal_plugins/releases/register.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/project_info/filter_targets.py]",
        "src/python/pants/build_graph/build_configuration.py",
        "src/python/pants/engine/internals/specs_rules.py",
        "src/python/pants/engine/internals/mapper.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/project_info/dependents.py]",
        "src/python/pants/vcs/changed.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/project_info/peek.py]",
        "pants-plugins/pants_explorer/server/graphql/**",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/project_info]",
        "src/python/pants/init/extension_loader.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/java/subsystems/java_infer.py]",
        "src/python/pants/jvm/dependency_inference/artifact_mapper.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/java/subsystems/junit.py]",
        "src/python/pants/jvm/test/junit.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/docker/target_types.py]",
        "pants-plugins/pants_explorer/server/graphql/query/conftest.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/codegen/export_codegen_goal.py]",
        "src/python/pants/core/register.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    (
        "[/__init__.py]",
        "src/python/pants/help/help_info_extracter.py",
        DEFAULT_DEPENDENTS_RULES,
    ),
    # Generic rule set:
    (
        # Applies for all targets in this subtree.
        "*",
        DEFAULT_DEPENDENTS_RULES,
    ),
)
