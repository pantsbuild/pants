# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.pex_info import PexInfo

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.subsystem.subsystem import Subsystem
from pants.util.collections import ensure_str_list


class PythonBinary(PythonTarget):
    """A Python binary.

    Python binaries are pex files, self-contained executable shell
    scripts that contain a complete Python environment capable of
    running the target. For more information about pex files see
    http://pantsbuild.github.io/python-readme.html#how-pex-files-work.

    :API: public
    """

    @classmethod
    def alias(cls):
        return "python_binary"

    class Defaults(Subsystem):

        options_scope = "python-binary"

        @classmethod
        def register_options(cls, register):
            super(PythonBinary.Defaults, cls).register_options(register)
            register(
                "--pex-emit-warnings",
                advanced=True,
                type=bool,
                default=True,
                fingerprint=True,
                help="Whether built pex binaries should emit pex warnings at runtime by default. "
                "Can be over-ridden by specifying the `emit_warnings` parameter of individual "
                "`{}` targets".format(PythonBinary.alias()),
            )

        @classmethod
        def should_emit_warnings(cls, override=None):
            return (
                override
                if override is not None
                else cls.global_instance().options.pex_emit_warnings
            )

    @classmethod
    def subsystems(cls):
        return super().subsystems() + (cls.Defaults,)

    # TODO(wickman) Consider splitting pex options out into a separate PexInfo builder that can be
    # attached to the binary target.  Ideally the PythonBinary target is agnostic about pex mechanics
    def __init__(
        self,
        sources=None,
        entry_point=None,
        inherit_path=False,  # pex option
        zip_safe=True,  # pex option
        always_write_cache=False,  # pex option
        ignore_errors=False,  # pex option
        shebang=None,  # pex option
        emit_warnings=None,  # pex option
        platforms=(),
        **kwargs
    ):
        """
        :param string entry_point: the default entry point for this binary.  if None, drops into the entry
          point that is defined by source. Something like
          "pants.bin.pants_exe:main", where "pants.bin.pants_exe" is the package
          name and "main" is the function name (if omitted, the module is
          executed directly, presuming it has a ``__main.py__``).
        :param sources: Zero or one source files. If more than one file is required, it should be put in
          a python_library which should be added to dependencies.
        :param inherit_path: inherit the sys.path of the environment that this binary runs in
        :param zip_safe: whether or not this binary is safe to run in compacted (zip-file) form
        :param always_write_cache: whether or not the .deps cache of this PEX file should always
          be written to disk.
        :param ignore_errors: should we ignore inability to resolve dependencies?
        :param str shebang: Use this shebang for the generated pex.
        :param bool emit_warnings: Whether or not to emit pex warnings.
        :param platforms: extra platforms to target when building this binary. If this is, e.g.,
          ``['current', 'linux-x86_64', 'macosx-10.4-x86_64']``, then when building the pex, then
          for any platform-dependent modules, Pants will include ``egg``\\s for Linux (64-bit Intel),
          Mac OS X (version 10.4 or newer), and the current platform (whatever is being used when
          making the PEX).
        """

        if inherit_path is False:
            inherit_path = "false"

        payload = Payload()
        payload.add_fields(
            {
                "entry_point": PrimitiveField(entry_point),
                "inherit_path": PrimitiveField(inherit_path),
                "zip_safe": PrimitiveField(bool(zip_safe)),
                "always_write_cache": PrimitiveField(bool(always_write_cache)),
                "ignore_errors": PrimitiveField(bool(ignore_errors)),
                "platforms": PrimitiveField(
                    tuple(ensure_str_list(platforms or [], allow_single_str=True))
                ),
                "shebang": PrimitiveField(shebang),
                "emit_warnings": PrimitiveField(self.Defaults.should_emit_warnings(emit_warnings)),
            }
        )

        super().__init__(sources=sources, payload=payload, **kwargs)

        if (not sources or not sources.files) and entry_point is None:
            raise TargetDefinitionException(
                self, "A python binary target must specify either a single source or entry_point."
            )

        if not isinstance(platforms, (list, tuple)) and not isinstance(platforms, str):
            raise TargetDefinitionException(self, "platforms must be a list, tuple or str.")

        if sources and sources.files and entry_point:
            entry_point_module = entry_point.split(":", 1)[0]
            entry_source = list(self.sources_relative_to_source_root())[0]
            source_entry_point = self.translate_source_path_to_py_module_specifier(entry_source)
            if entry_point_module != source_entry_point:
                raise TargetDefinitionException(
                    self,
                    "Specified both source and entry_point but they do not agree: {} vs {}".format(
                        source_entry_point, entry_point_module
                    ),
                )

    @property
    def platforms(self):
        return self.payload.platforms

    @classmethod
    def translate_source_path_to_py_module_specifier(self, source: str) -> str:
        source_base, _ = os.path.splitext(source)
        return source_base.replace(os.path.sep, ".")

    @property
    def entry_point(self):
        if self.payload.entry_point:
            return self.payload.entry_point
        elif self.payload.sources.source_paths:
            assert len(self.payload.sources.source_paths) == 1
            entry_source = list(self.sources_relative_to_source_root())[0]
            return self.translate_source_path_to_py_module_specifier(entry_source)
        else:
            return None

    @property
    def shebang(self):
        return self.payload.shebang

    @property
    def pexinfo(self):
        info = PexInfo.default()
        info.zip_safe = self.payload.zip_safe
        info.always_write_cache = self.payload.always_write_cache
        info.inherit_path = self.payload.inherit_path
        info.entry_point = self.entry_point
        info.ignore_errors = self.payload.ignore_errors
        info.emit_warnings = self.payload.emit_warnings
        return info
