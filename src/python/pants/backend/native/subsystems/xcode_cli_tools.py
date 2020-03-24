# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.native.config.environment import Assembler, CCompiler, CppCompiler, Linker
from pants.engine.rules import rule
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_method, memoized_property

MIN_OSX_SUPPORTED_VERSION = "10.11"


MIN_OSX_VERSION_ARG = f"-mmacosx-version-min={MIN_OSX_SUPPORTED_VERSION}"


class XCodeCLITools(Subsystem):
    """Subsystem to detect and provide the XCode command line developer tools.

    This subsystem exists to give a useful error message if the tools aren't installed, and because
    the install location may not be on the PATH when Pants is invoked.
    """

    options_scope = "xcode-cli-tools"

    _REQUIRED_FILES = {
        "bin": ["as", "cc", "c++", "clang", "clang++", "ld", "lipo"],
        # Any of the entries that would be here are not directly below the 'include' or 'lib' dirs, and
        # we haven't yet encountered an invalid XCode/CLI tools installation which has the include dirs,
        # but incorrect files. These would need to be updated if such an issue arises.
        "include": [],
        "lib": [],
    }

    INSTALL_PREFIXES_DEFAULT = [
        # Prefer files from this installation directory, if available. This doesn't appear to be
        # populated with e.g. header files on travis.
        "/usr",
        # Populated by the XCode CLI tools.
        "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr",
        # Populated by the XCode app. These are derived from using the -v or -H switches invoking the
        # osx clang compiler.
        "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr",
        "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/clang/9.1.0",
        "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk/usr",
    ]

    class XCodeToolsUnavailable(Exception):
        """Thrown if the XCode CLI tools could not be located."""

    class XCodeToolsInvalid(Exception):
        """Thrown if a method within this subsystem requests a nonexistent tool."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--install-prefixes",
            type=list,
            default=cls.INSTALL_PREFIXES_DEFAULT,
            fingerprint=True,
            advanced=True,
            help="Locations to search for resources from the XCode CLI tools, including a "
            "compiler, linker, header files, and some libraries. "
            "Under this directory should be some selection of these subdirectories: "
            f"{cls._REQUIRED_FILES.keys()}.",
        )

    @memoized_property
    def _all_existing_install_prefixes(self):
        return [pfx for pfx in self.get_options().install_prefixes if is_readable_dir(pfx)]

    # NB: We use @memoized_method in this file for methods which may raise.
    @memoized_method
    def _get_existing_subdirs(self, subdir_name):
        # TODO(#6143): We should attempt to use ParseSearchDirs here or find some documentation on which
        # directories we should be adding to the include path, and why. If we do need to manually
        # specify paths, use ArchiveFileMapper instead of doing all that logic over again in this file.
        maybe_subdirs = [
            os.path.join(pfx, subdir_name) for pfx in self._all_existing_install_prefixes
        ]
        existing_dirs = [
            existing_dir for existing_dir in maybe_subdirs if is_readable_dir(existing_dir)
        ]

        required_files_for_dir = self._REQUIRED_FILES.get(subdir_name)
        if required_files_for_dir:
            for fname in required_files_for_dir:
                found = False
                for subdir in existing_dirs:
                    full_path = os.path.join(subdir, fname)
                    if os.path.isfile(full_path):
                        found = True
                        continue

                if not found:
                    raise self.XCodeToolsUnavailable(
                        f"File '{fname}' in subdirectory '{subdir_name}' does not exist at any of the "
                        "specified prefixes. This file is required to build native code on this platform. You "
                        "may need to install the XCode command line developer tools from the Mac App Store.\n\n"
                        "If the XCode tools are installed and you are still seeing this message, please file "
                        "an issue at https://github.com/pantsbuild/pants/issues/new describing your "
                        "OSX environment and which file could not be found.\n"
                        f"The existing install prefixes were: {self._all_existing_install_prefixes}. These can "
                        f"be extended with --{self.get_options_scope_equivalent_flag_component()}-install-"
                        f"prefixes."
                    )

        return existing_dirs

    @memoized_method
    def path_entries(self):
        return self._get_existing_subdirs("bin")

    @memoized_method
    def lib_dirs(self):
        return self._get_existing_subdirs("lib")

    @memoized_method
    def include_dirs(self, include_cpp_inc=False):
        return self._get_existing_subdirs("include")

    @memoized_method
    def assembler(self) -> Assembler:
        return Assembler(
            path_entries=self.path_entries(),
            exe_filename="as",
            runtime_library_dirs=(),
            extra_args=(),
        )

    @memoized_method
    def linker(self) -> Linker:
        return Linker(
            path_entries=self.path_entries(),
            exe_filename="ld",
            runtime_library_dirs=(),
            linking_library_dirs=(),
            extra_args=(MIN_OSX_VERSION_ARG,),
            extra_object_files=(),
        )

    @memoized_method
    def c_compiler(self) -> CCompiler:
        return CCompiler(
            path_entries=self.path_entries(),
            exe_filename="clang",
            runtime_library_dirs=self.lib_dirs(),
            include_dirs=self.include_dirs(),
            extra_args=(MIN_OSX_VERSION_ARG,),
        )

    @memoized_method
    def cpp_compiler(self) -> CppCompiler:
        return CppCompiler(
            path_entries=self.path_entries(),
            exe_filename="clang++",
            runtime_library_dirs=self.lib_dirs(),
            include_dirs=self.include_dirs(include_cpp_inc=True),
            extra_args=(MIN_OSX_VERSION_ARG,),
        )


@rule
def get_assembler(xcode_cli_tools: XCodeCLITools) -> Assembler:
    return xcode_cli_tools.assembler()


@rule
def get_ld(xcode_cli_tools: XCodeCLITools) -> Linker:
    return xcode_cli_tools.linker()


@rule
def get_clang(xcode_cli_tools: XCodeCLITools) -> CCompiler:
    return xcode_cli_tools.c_compiler()


@rule
def get_clang_plusplus(xcode_cli_tools: XCodeCLITools) -> CppCompiler:
    return xcode_cli_tools.cpp_compiler()


def create_xcode_cli_tools_rules():
    return [
        get_assembler,
        get_ld,
        get_clang,
        get_clang_plusplus,
    ]
