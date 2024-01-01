# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    SingleSourceField,
    SpecialCasedDependencies,
    StringField,
    Target,
)
from pants.util.docutil import bin_name
from pants.util.strutil import help_text


class MakeselfArthiveLabel(StringField):
    alias = "label"


class MakeselfArchiveStartupScript(SingleSourceField):
    alias = "startup_script"
    help = help_text(
        """
        Set the startup script, i.e. what gets run when executing `./my_archive.run`,
        to an address of shell source or a target that can be packaged, e.g. `pex_binary`.
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


class MakeselfArchiveOutputPath(OutputPathField):
    pass


class MakeselfArchiveTarget(Target):
    alias = "makeself_archive"
    core_fields = (
        MakeselfArthiveLabel,
        MakeselfArchiveStartupScript,
        MakeselfArchiveFilesField,
        MakeselfArchivePackagesField,
        MakeselfArchiveOutputPath,
        *COMMON_TARGET_FIELDS,
    )
    help = help_text(
        """
        Self-extractable archive on Unix using [makeself](https://github.com/megastep/makeself)
        tool.
        """
    )
