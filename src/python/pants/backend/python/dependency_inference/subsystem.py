# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum

from pants.option.option_types import BoolOption, EnumOption, IntOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap


class UnownedDependencyUsage(Enum):
    """What action to take when an inferred dependency is unowned."""

    RaiseError = "error"
    LogWarning = "warning"
    DoNothing = "ignore"


class InitFilesInference(Enum):
    """How to handle inference for __init__.py files."""

    always = "always"
    content_only = "content_only"
    never = "never"


class AmbiguityResolution(Enum):
    """How to resolve ambiguous symbol ownership."""

    none = "none"
    by_source_root = "by_source_root"


class PythonInferSubsystem(Subsystem):
    options_scope = "python-infer"
    help = "Options controlling which dependencies will be inferred for Python targets."

    imports = BoolOption(
        default=True,
        help=softwrap(
            """
            Infer a target's imported dependencies by parsing import statements from sources.

            To ignore a false positive, you can either put `# pants: no-infer-dep` on the line of
            the import or put `!{bad_address}` in the `dependencies` field of your target.
            """
        ),
    )
    string_imports = BoolOption(
        default=False,
        help=softwrap(
            """
            Infer a target's dependencies based on strings that look like dynamic
            dependencies, such as Django settings files expressing dependencies as strings.

            To ignore a false positive, you can either put `# pants: no-infer-dep` on the line of
            the string or put `!{bad_address}` in the `dependencies` field of your target.
            """
        ),
    )
    string_imports_min_dots = IntOption(
        default=2,
        help=softwrap(
            """
            If --string-imports is True, treat valid-looking strings with at least this many
            dots in them as potential dynamic dependencies. E.g., `'foo.bar.Baz'` will be
            treated as a potential dependency if this option is set to 2 but not if set to 3.
            """
        ),
    )
    assets = BoolOption(
        default=False,
        help=softwrap(
            """
            Infer a target's asset dependencies based on strings that look like Posix
            filepaths, such as those given to `open` or `pkgutil.get_data`.

            To ignore a false positive, you can either put `# pants: no-infer-dep` on the line of
            the string or put `!{bad_address}` in the `dependencies` field of your target.
            """
        ),
    )
    assets_min_slashes = IntOption(
        default=1,
        help=softwrap(
            """
            If --assets is True, treat valid-looking strings with at least this many forward
            slash characters as potential assets. E.g. `'data/databases/prod.db'` will be
            treated as a potential candidate if this option is set to 2 but not to 3.
            """
        ),
    )
    init_files = EnumOption(
        help=softwrap(
            f"""
            Infer a target's dependencies on any `__init__.py` files in the packages
            it is located in (recursively upward in the directory structure).

            Even if this is set to `never` or `content_only`, Pants will still always include any
            ancestor `__init__.py` files in the sandbox. Only, they will not be "proper"
            dependencies, e.g. they will not show up in `{bin_name()} dependencies` and their own
            dependencies will not be used.

            By default, Pants only adds a "proper" dependency if there is content in the
            `__init__.py` file. This makes sure that dependencies are added when likely necessary
            to build, while also avoiding adding unnecessary dependencies. While accurate, those
            unnecessary dependencies can complicate setting metadata like the
            `interpreter_constraints` and `resolve` fields.
            """
        ),
        default=InitFilesInference.content_only,
    )
    conftests = BoolOption(
        default=True,
        help=softwrap(
            """
            Infer a test target's dependencies on any conftest.py files in the current
            directory and ancestor directories.
            """
        ),
    )
    entry_points = BoolOption(
        default=True,
        help=softwrap(
            """
            Infer dependencies on targets' entry points, e.g. `pex_binary`'s
            `entry_point` field, `python_awslambda`'s `handler` field and
            `python_distribution`'s `entry_points` field.
            """
        ),
    )
    unowned_dependency_behavior = EnumOption(
        default=UnownedDependencyUsage.LogWarning,
        help=softwrap(
            """
            How to handle imports that don't have an inferrable owner.

            Usually when an import cannot be inferred, it represents an issue like Pants not being
            properly configured, e.g. targets not set up. Often, missing dependencies will result
            in confusing runtime errors like `ModuleNotFoundError`, so this option can be helpful
            to error more eagerly.

            To ignore any false positives, either add `# pants: no-infer-dep` to the line of the
            import or put the import inside a `try: except ImportError:` block.
            """
        ),
    )
    ambiguity_resolution = EnumOption(
        default=AmbiguityResolution.none,
        help=softwrap(
            f"""
            When multiple sources provide the same symbol, how to choose the provider to use.

            `{AmbiguityResolution.none.value}`: Do not attempt to resolve this ambiguity.
            No dependency will be inferred, and warnings will be logged.

            `{AmbiguityResolution.by_source_root.value}`:  Choose the provider with the closest
            common ancestor to the consumer's source root.  If the provider is under the same
            source root then this will be the source root itself.
            This is useful when multiple projects in different source roots provide the same
            symbols (because of repeated first-party module paths or overlapping
            requirements.txt) and you want to resolve the ambiguity locally in each project.
            """
        ),
    )

    ignored_unowned_imports = StrListOption(
        default=[],
        help=softwrap(
            """Unowned imports that should be ignored.

            If there are any unowned import statements and adding the `# pants: no-infer-dep`
            to the lines of the import is impractical, you can instead provide a list of imports
            that Pants should ignore. You can declare a specific import or a path to a package
            if you would like any of the package imports to be ignored.

            For example, you could ignore all the following imports of the code

                ```
                import src.generated.app
                from src.generated.app import load
                from src.generated.app import start
                from src.generated.client import connect
                ```

            by setting `ignored-unowned-imports=["src.generated.app", "src.generated.client.connect"]`.
        """
        ),
    )
