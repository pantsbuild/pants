# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    OptionalSingleSourceField,
    StringField,
    StringSequenceField,
    Target,
)

# TODO: This runs into https://github.com/pantsbuild/pants/issues/13587
# class PyOxidizerEntryPointField(PexEntryPointField):
#     pass


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
        PyOxidizerConfigSourceField,
        PyOxidizerDependenciesField,
        PyOxidizerEntryPointField,
        PyOxidizerUnclassifiedResources,
    )
    help = (
        "A single-file Python executable with a Python interpreter embedded, built via PyOxidizer."
    )
