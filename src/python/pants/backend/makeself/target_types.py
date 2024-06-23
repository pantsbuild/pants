# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.docutil import bin_name
from pants.util.strutil import help_text


class MakeselfArthiveLabelField(StringField):
    alias = "label"
    help = help_text(
        """
        An arbitrary text string describing the package. It will be displayed while extracting
        the files.
        """
    )


class MakeselfArchiveStartupScriptField(StringSequenceField):
    alias = "startup_script"
    required = False
    help = help_text(
        """
        The startup script, i.e. what gets run when executing `./my_archive.run`.

        Examples:
        - `["startup.sh"]`
        - `["echo", "Running makeself archieve"]`
        """
    )


class MakeselfArchiveFilesField(SpecialCasedDependencies):
    alias = "files"
    help = help_text(
        """
        Addresses to any `file`, `files`, or `relocated_files` targets to include in the
        archive, e.g. `["resources:logo"]`.

        This is useful to include any loose files, like data files,
        image assets, or config files.

        This will ignore any targets that are not `file`, `files`, or
        `relocated_files` targets.

        If you instead want those files included in any packages specified in the `packages`
        field for this target, then use a `resource` or `resources` target and have the original
        package depend on the resources.
        """
    )


class MakeselfArchivePackagesField(SpecialCasedDependencies):
    alias = "packages"
    help = help_text(
        f"""
        Addresses to any targets that can be built with `{bin_name()} package`,
        e.g. `["project:app"]`.

        Pants will build the assets as if you had run `{bin_name()} package`.
        It will include the results in your archive using the same name they
        would normally have, but without the `--distdir` prefix (e.g. `dist/`).

        You can include anything that can be built by `{bin_name()} package`,
        e.g. a `pex_binary`, `python_awslambda`, or even another `makeself_archive`.
        """
    )


class MakeselfArchiveOutputPathField(OutputPathField):
    pass


class MakeselfArchiveArgsField(StringSequenceField):
    alias = "args"
    required = False
    help = help_text(
        """
        [Arguments](https://github.com/megastep/makeself#usage) to pass
        to the `makeself` script when building this archive. These are passed
        before any file paths.
        """
    )


class MakeselfArchiveToolsField(StringSequenceField):
    alias = "tools"
    default = ()
    help = help_text(
        """
        Specify required executable tools that might be used.

        Only the tools explicitly provided will be available on the search PATH,
        and these tools must be found on the paths provided by
        `[shell-setup].executable_search_paths` (which defaults to the system PATH).
        """
    )


class MakeselfArchiveTarget(Target):
    alias = "makeself_archive"
    core_fields = (
        MakeselfArthiveLabelField,
        MakeselfArchiveStartupScriptField,
        MakeselfArchiveFilesField,
        MakeselfArchivePackagesField,
        MakeselfArchiveOutputPathField,
        MakeselfArchiveArgsField,
        MakeselfArchiveToolsField,
        *COMMON_TARGET_FIELDS,
    )
    help = help_text(
        """
        Self-extractable archive on Unix using [makeself](https://github.com/megastep/makeself)
        tool.
        """
    )
