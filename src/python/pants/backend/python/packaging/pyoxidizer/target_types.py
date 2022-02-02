# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

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
    help = dedent(
        """Set the entry point, i.e. what gets run when executing `./my_app`, to a module.
        This represents the content of PyOxidizer's `python_config.run_module` and leaving this
        field empty will create a REPL binary.
        It is specified with the full module declared: 'path.to.module'.
        This field is passed into the PyOxidizer config as-is, and does not undergo validation checking.
        """
    )


class PyOxidizerDependenciesField(Dependencies):
    pass


class PyOxidizerUnclassifiedResources(StringSequenceField):
    alias = "filesystem_resources"
    help = dedent(
        """Adds support for listing dependencies that MUST be installed to the filesystem (e.g. Numpy)
        https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer_packaging_additional_files.html#installing-unclassified-files-on-the-filesystem"""
    )


# TODO: I think this should be automatically picked up, like isort or black configs - just not sure how to access the source root from the pyoxidizer_binary target
# In fact, should there even be a way to run this without a PyOxidizer config? The config can get complicated, so the default probably runs into many edge cases.
class PyOxidizerConfigSourceField(OptionalSingleSourceField):
    alias = "template"
    default = None
    required = False
    expected_file_extensions = (".bzlt",)
    expected_num_files = range(0, 2)
    help = dedent(
        """
        Adds support for passing in a custom configuration and only injecting certain parameters from the Pants build process.
        Path is relative to the BUILD file's directory.
        Template requires a .bzlt extension. Parameters must be prefixed by $ or surrounded with ${ }
        Template parameters:
            - RUN_MODULE - The re-formatted entry_point passed to this target (or None).
            - NAME - This target's name.
            - WHEELS - All python distributions passed to this target (or []).
            - UNCLASSIFIED_RESOURCE_INSTALLATION - This will populate a snippet of code to correctly inject the targets filesystem_resources.
        """
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
    help = "The `pyoxidizer_binary` target describes how to build a single file executable."
