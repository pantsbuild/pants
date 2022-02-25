# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    OptionalSingleSourceField,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.docutil import bin_name


class PyOxidizerOutputPathField(OutputPathField):
    help = (
        "Where the built directory tree should be located.\n\n"
        "If undefined, this will use the path to the BUILD file, followed by the target name. "
        "For example, `src/python/project:bin` would be "
        "`src.python.project/bin/`.\n\n"
        "Regardless of whether you use the default or set this field, the path will end with "
        "PyOxidizer's file format of `<platform>/{debug,release}/install/<binary_name>`, where "
        "`platform` is a Rust platform triplet like `aarch-64-apple-darwin` and `binary_name` is "
        "the `name` of the `pyoxidizer_target`. So, using the default for this field, the target "
        "`src/python/project:bin` might have a final path like "
        "`src.python.project/bin/aarch-64-apple-darwin/release/bin`.\n\n"
        f"When running `{bin_name()} package`, this path will be prefixed by `--distdir` (e.g. "
        "`dist/`).\n\n"
        "Warning: setting this value risks naming collisions with other package targets you may "
        "have."
    )


class PyOxidizerEntryPointField(StringField):
    alias = "entry_point"
    default = None
    help = (
        "Set the entry point, i.e. what gets run when executing `./my_app`, to a module. "
        "This represents the content of PyOxidizer's `python_config.run_module` and leaving this "
        "field empty will create a REPL binary.\n\n"
        "It is specified with the full module declared: 'path.to.module'.\n\n"
        "This field is passed into the PyOxidizer config as-is, and does not undergo validation "
        "checking."
    )


class PyOxidizerDependenciesField(Dependencies):
    pass


class PyOxidizerUnclassifiedResources(StringSequenceField):
    alias = "filesystem_resources"
    help = (
        "Adds support for listing dependencies that MUST be installed to the filesystem "
        "(e.g. Numpy). See"
        "https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer_packaging_additional_files.html#installing-unclassified-files-on-the-filesystem"
    )


# TODO: I think this should be automatically picked up, like isort or black configs - just not sure how to access the source root from the pyoxidizer_binary target
# In fact, should there even be a way to run this without a PyOxidizer config? The config can get complicated, so the default probably runs into many edge cases.
class PyOxidizerConfigSourceField(OptionalSingleSourceField):
    alias = "template"
    expected_file_extensions = (".bzlt",)
    help = (
        "If set, will use your custom configuration rather than using Pants's default template.\n\n"
        "The path is relative to the BUILD file's directory, and it must end in `.blzt`.\n\n"
        "All parameters must be prefixed by $ or surrounded with ${ }.\n\n"
        "Available template parameters:\n\n"
        "  * RUN_MODULE - The re-formatted entry_point passed to this target (or None).\n"
        "  * NAME - This target's name.\n"
        "  * WHEELS - All python distributions passed to this target (or []).\n"
        "  * UNCLASSIFIED_RESOURCE_INSTALLATION - This will populate a snippet of code to "
        "correctly inject the targets filesystem_resources."
    )


class PyOxidizerTarget(Target):
    alias = "pyoxidizer_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PyOxidizerOutputPathField,
        PyOxidizerConfigSourceField,
        PyOxidizerDependenciesField,
        PyOxidizerEntryPointField,
        PyOxidizerUnclassifiedResources,
    )
    help = (
        "A single-file Python executable with a Python interpreter embedded, built via PyOxidizer."
    )
