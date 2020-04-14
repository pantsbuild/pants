# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import logging
import os
import re
import sys
import sysconfig
import traceback
from contextlib import closing
from types import CoroutineType
from typing import Any, Iterable, List, NamedTuple, Tuple, Type, cast

import cffi
import pkg_resources

from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
from pants.engine.fs import (
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    DirectoryWithPrefixToStrip,
    FileContent,
    FilesContent,
    InputFilesContent,
    MaterializeDirectoriesResult,
    MaterializeDirectoryResult,
    PathGlobs,
    Snapshot,
    SnapshotSubset,
    UrlToFetch,
)
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveProcessResult
from pants.engine.isolated_process import FallibleProcessResultWithPlatform, MultiPlatformProcess
from pants.engine.objects import union
from pants.engine.platform import Platform
from pants.engine.selectors import Get
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import read_file, safe_mkdir, safe_mkdtemp
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.meta import SingletonMetaclass
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


NATIVE_ENGINE_MODULE = "native_engine"

# NB: This is a "patch" applied to CFFI's generated sources to remove the ifdefs that would
# usually cause only one of the two module definition functions to be defined. Instead, we define
# both. Since `patch` is not available in all relevant environments (notably, many docker images),
# this is accomplished using string replacement. To (re)-generate this patch, fiddle with the
# unmodified output of `ffibuilder.emit_c_code`.
CFFI_C_PATCH_BEFORE = """
#  ifdef _MSC_VER
     PyMODINIT_FUNC
#  if PY_MAJOR_VERSION >= 3
     PyInit_native_engine(void) { return NULL; }
#  else
     initnative_engine(void) { }
#  endif
#  endif
#elif PY_MAJOR_VERSION >= 3
PyMODINIT_FUNC
PyInit_native_engine(void)
{
  return _cffi_init("native_engine", 0x2601, &_cffi_type_context);
}
#else
PyMODINIT_FUNC
initnative_engine(void)
{
  _cffi_init("native_engine", 0x2601, &_cffi_type_context);
}
#endif
"""
CFFI_C_PATCH_AFTER = """
#endif

PyObject* // PyMODINIT_FUNC for PY3
wrapped_PyInit_native_engine(void)
{
  return _cffi_init("native_engine", 0x2601, &_cffi_type_context);
}

void // PyMODINIT_FUNC for PY2
wrapped_initnative_engine(void)
{
  _cffi_init("native_engine", 0x2601, &_cffi_type_context);
}
"""


def get_build_cflags():
    """Synthesize a CFLAGS env var from the current python env for building of C modules."""
    return "{} {} -I{}".format(
        sysconfig.get_config_var("BASECFLAGS"),
        sysconfig.get_config_var("OPT"),
        sysconfig.get_path("include"),
    )


_preprocessor_directive_replacement_stub = "HACKY_CDEF_PREPROCESSOR_DIRECTIVE"


def _hackily_rewrite_scheduler_bindings(bindings):
    # We need #include lines and header guards in the generated C source file, but this won't parse in
    # the .cdef call (it can't handle any preprocessor directives), so we put them behind a comment
    # line for now.
    preprocessor_directives_removed = re.sub(
        r"^(#.*)$",
        r"// {}: \1".format(_preprocessor_directive_replacement_stub),
        bindings,
        flags=re.MULTILINE,
    )
    # This is an opaque struct member, which is not exposed to the FFI (and errors if this is
    # removed).
    hidden_vec_pyresult = re.sub(
        r"^.*Vec_PyResult nodes;.*$",
        "// Additional fields removed",
        preprocessor_directives_removed,
        flags=re.MULTILINE,
    )
    # The C bindings generated for tuple structs by default use _0, _1, etc for members. The cffi
    # library doesn't allow leading underscores on members like that, so we produce e.g. tup_0
    # instead. This works because the header file produced by cbindgen is reliably formatted.
    positional_fields_prefixed = re.sub(
        r"(_[0-9]+;)$", r"tup\1", hidden_vec_pyresult, flags=re.MULTILINE
    )
    # Avoid clashing with common python symbols (we again assume the generated bindings are reliably
    # formatted).
    special_python_symbols_mangled = re.sub(r"\bid\b", "id_", positional_fields_prefixed)
    return special_python_symbols_mangled


def _hackily_recreate_includes_for_bindings(bindings):
    # Undo the mangling we did for preprocessor directives such as #include lines previously so that
    # the generated C source file will have access to the necessary includes for the types produced by
    # cbindgen.
    return re.sub(
        r"^// {}: (.*)$".format(_preprocessor_directive_replacement_stub),
        r"\1",
        bindings,
        flags=re.MULTILINE,
    )


def bootstrap_c_source(scheduler_bindings_path, output_dir, module_name=NATIVE_ENGINE_MODULE):
    """Bootstrap an external CFFI C source file."""

    safe_mkdir(output_dir)

    with temporary_dir() as tempdir:
        temp_output_prefix = os.path.join(tempdir, module_name)
        real_output_prefix = os.path.join(output_dir, module_name)
        temp_c_file = "{}.c".format(temp_output_prefix)
        c_file = "{}.c".format(real_output_prefix)
        env_script = "{}.cflags".format(real_output_prefix)

        # Preprocessor directives won't parse in the .cdef calls, so we have to hide them for now.
        scheduler_bindings_content = read_file(scheduler_bindings_path)
        scheduler_bindings = _hackily_rewrite_scheduler_bindings(scheduler_bindings_content)

        ffibuilder = cffi.FFI()
        ffibuilder.cdef(scheduler_bindings)
        ffibuilder.cdef(_FFISpecification.format_cffi_externs())
        ffibuilder.set_source(module_name, scheduler_bindings)
        ffibuilder.emit_c_code(temp_c_file)

        # Work around https://github.com/rust-lang/rust/issues/36342 by renaming initnative_engine to
        # wrapped_initnative_engine so that the rust code can define the symbol initnative_engine.
        #
        # If we dont do this, we end up at the mercy of the implementation details of rust's stripping
        # and LTO. In the past we have found ways to trick it into not stripping symbols which was handy
        # (it kept the binary working) but inconvenient (it was relying on unspecified behavior, it meant
        # our binaries couldn't be stripped which inflated them by 2~3x, and it reduced the amount of LTO
        # we could use, which led to unmeasured performance hits).
        #
        # We additionally remove the ifdefs that apply conditional `init` logic for Py2 vs Py3, in order
        # to define a module that is loadable by either 2 or 3.
        # TODO: Because PyPy uses the same `init` function name regardless of the python version, this
        # trick does not work there: we leave its conditional in place.
        file_content = read_file(temp_c_file)
        if CFFI_C_PATCH_BEFORE not in file_content:
            raise Exception("The patch for the CFFI generated code will not apply cleanly.")
        file_content = file_content.replace(CFFI_C_PATCH_BEFORE, CFFI_C_PATCH_AFTER)

        # Extract the preprocessor directives we had to hide to get the .cdef call to parse.
        file_content = _hackily_recreate_includes_for_bindings(file_content)

    _replace_file(c_file, file_content)

    # Write a shell script to be sourced at build time that contains inherited CFLAGS.
    _replace_file(env_script, get_build_cflags())


def _replace_file(path, content):
    """Writes a file if it doesn't already exist with the same content.

    This is useful because cargo uses timestamps to decide whether to compile things.
    """
    if os.path.exists(path):
        with open(path, "r") as f:
            if content == f.read():
                print("Not overwriting {} because it is unchanged".format(path), file=sys.stderr)
                return

    with open(path, "w") as f:
        f.write(content)


class _ExternSignature(NamedTuple):
    """A type signature for a python-defined FFI function."""

    return_type: str
    method_name: str
    arg_types: Tuple[str, ...]

    def pretty_print(self):
        return "  {ret}\t{name}({args});".format(
            ret=self.return_type, name=self.method_name, args=", ".join(self.arg_types)
        )


def _extern_decl(return_type, arg_types):
    """A decorator for methods corresponding to extern functions. All types should be strings.

    The _FFISpecification class is able to automatically convert these into method declarations for
    cffi.
    """

    def wrapper(func):
        signature = _ExternSignature(
            return_type=str(return_type), method_name=str(func.__name__), arg_types=tuple(arg_types)
        )
        func.extern_signature = signature
        return func

    return wrapper


class _FFISpecification(object):
    def __init__(self, ffi, lib):
        self._ffi = ffi
        self._lib = lib

    @memoized_classproperty
    def _extern_fields(cls):
        return {
            field_name: f
            for field_name, f in cls.__dict__.items()
            if hasattr(f, "extern_signature")
        }

    @classmethod
    def format_cffi_externs(cls):
        """Generate stubs for the cffi bindings from @_extern_decl methods."""
        extern_decls = [f.extern_signature.pretty_print() for _, f in cls._extern_fields.items()]
        return 'extern "Python" {\n' + "\n".join(extern_decls) + "\n}\n"

    def register_cffi_externs(self, native):
        """Registers the @_extern_decl methods with our ffi instance.

        Also establishes an `onerror` handler for each extern method which stores any exception in the
        `native` object so that it can be retrieved later. See
        https://cffi.readthedocs.io/en/latest/using.html#extern-python-reference for more info.
        """
        native.reset_cffi_extern_method_runtime_exceptions()

        def exc_handler(exc_type, exc_value, traceback):
            error_info = native.CFFIExternMethodRuntimeErrorInfo(exc_type, exc_value, traceback)
            native.add_cffi_extern_method_runtime_exception(error_info)

        for field_name, _ in self._extern_fields.items():
            bound_method = getattr(self, field_name)
            self._ffi.def_extern(onerror=exc_handler)(bound_method)

    def to_py_str(self, msg_ptr, msg_len):
        return bytes(self._ffi.buffer(msg_ptr, msg_len)).decode()

    @classmethod
    def call(cls, c, func, args):
        try:
            val = func(*args)
            is_throw = False
        except Exception as e:
            val = e
            is_throw = True
            e._formatted_exc = traceback.format_exc()

        return PyResult(is_throw, c.to_value(val))

    @_extern_decl("TypeId", ["ExternContext*", "Handle*"])
    def extern_get_type_for(self, context_handle, val):
        """Return a representation of the object's type."""
        c = self._ffi.from_handle(context_handle)
        obj = self._ffi.from_handle(val[0])
        type_id = c.to_id(type(obj))
        return TypeId(type_id)

    @_extern_decl("Handle", ["ExternContext*", "TypeId"])
    def extern_get_handle_from_type_id(self, context_handle, ty):
        c = self._ffi.from_handle(context_handle)
        obj = c.from_id(ty.tup_0)
        return c.to_value(obj)

    @_extern_decl("bool", ["ExternContext*", "TypeId"])
    def extern_is_union(self, context_handle, type_id):
        """Return whether or not a type is a member of a union."""
        c = self._ffi.from_handle(context_handle)
        input_type = c.from_id(type_id.tup_0)
        return union.is_instance(input_type)

    _do_raise_keyboardinterrupt_on_identify = bool(
        os.environ.get("_RAISE_KEYBOARDINTERRUPT_IN_CFFI_IDENTIFY", False)
    )

    @_extern_decl("Ident", ["ExternContext*", "Handle*"])
    def extern_identify(self, context_handle, val):
        """Return a representation of the object's identity, including a hash and TypeId.

        `extern_get_type_for()` also returns a TypeId, but doesn't hash the object -- this allows
        that method to be used on unhashable objects. `extern_identify()` returns a TypeId as well
        to avoid having to make two separate Python calls when interning a Python object in
        interning.rs, which requires both the hash and type.
        """
        # NB: This check is exposed for testing error handling in CFFI methods. This code path should
        # never be active in normal pants usage.
        if self._do_raise_keyboardinterrupt_on_identify:
            raise KeyboardInterrupt("ctrl-c interrupted execution of a cffi method!")
        c = self._ffi.from_handle(context_handle)
        obj = self._ffi.from_handle(val[0])
        return c.identify(obj)

    @_extern_decl("_Bool", ["ExternContext*", "Handle*", "Handle*"])
    def extern_equals(self, context_handle, val1, val2):
        """Return true if the given Handles are __eq__."""
        return self._ffi.from_handle(val1[0]) == self._ffi.from_handle(val2[0])

    @_extern_decl("Handle", ["ExternContext*", "Handle*"])
    def extern_clone_val(self, context_handle, val):
        """Clone the given Handle."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(self._ffi.from_handle(val[0]))

    @_extern_decl("void", ["ExternContext*", "DroppingHandle*", "uint64_t"])
    def extern_drop_handles(self, context_handle, handles_ptr, handles_len):
        """Drop the given Handles."""
        c = self._ffi.from_handle(context_handle)
        handles = self._ffi.unpack(handles_ptr, handles_len)
        c.drop_handles(handles)

    @_extern_decl("Buffer", ["ExternContext*", "TypeId"])
    def extern_type_to_str(self, context_handle, type_id):
        """Given a TypeId, write type.__name__ and return it."""
        c = self._ffi.from_handle(context_handle)
        return c.utf8_buf(str(c.from_id(type_id.tup_0).__name__))

    # If we try to pass a None to the CFFI layer, it will silently fail
    # in a weird way. So instead we use the empty string/bytestring as
    # a de-facto null value, in both `extern_val_to_str` and
    # `extern_val_to_bytes`.
    @_extern_decl("Buffer", ["ExternContext*", "Handle*"])
    def extern_val_to_bytes(self, context_handle, val):
        """Given a Handle for `obj`, write bytes(obj) and return it."""
        c = self._ffi.from_handle(context_handle)
        v = c.from_value(val[0])
        v_bytes = b"" if v is None else bytes(v)
        return c.buf(v_bytes)

    @_extern_decl("Buffer", ["ExternContext*", "Handle*"])
    def extern_val_to_str(self, context_handle, val):
        """Given a Handle for `obj`, write str(obj) and return it."""
        c = self._ffi.from_handle(context_handle)
        v = c.from_value(val[0])
        v_str = "" if v is None else str(v)
        return c.utf8_buf(v_str)

    @_extern_decl("_Bool", ["ExternContext*", "Handle*"])
    def extern_val_to_bool(self, context_handle, val):
        """Given a Handle for `obj`, write bool(obj) and return it."""
        c = self._ffi.from_handle(context_handle)
        v = c.from_value(val[0])
        return bool(v)

    @_extern_decl("Handle", ["ExternContext*", "Handle**", "uint64_t"])
    def extern_store_tuple(self, context_handle, vals_ptr, vals_len):
        """Given storage and an array of Handles, return a new Handle to represent the list."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(
            tuple(c.from_value(val[0]) for val in self._ffi.unpack(vals_ptr, vals_len))
        )

    @_extern_decl("Handle", ["ExternContext*", "Handle**", "uint64_t"])
    def extern_store_set(self, context_handle, vals_ptr, vals_len):
        """Given storage and an array of Handles, return a new Handle to represent the set."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(
            FrozenOrderedSet(c.from_value(val[0]) for val in self._ffi.unpack(vals_ptr, vals_len))
        )

    @_extern_decl("Handle", ["ExternContext*", "Handle**", "uint64_t"])
    def extern_store_dict(self, context_handle, vals_ptr, vals_len):
        """Given storage and an array of Handles, return a new Handle to represent the dict.

        Array of handles alternates keys and values (i.e. key0, value0, key1, value1, ...).

        It is assumed that an even number of values were passed.
        """
        c = self._ffi.from_handle(context_handle)
        tup = tuple(c.from_value(val[0]) for val in self._ffi.unpack(vals_ptr, vals_len))
        d = dict()
        for i in range(0, len(tup), 2):
            d[tup[i]] = tup[i + 1]
        return c.to_value(d)

    @_extern_decl("Handle", ["ExternContext*", "uint8_t*", "uint64_t"])
    def extern_store_bytes(self, context_handle, bytes_ptr, bytes_len):
        """Given a context and raw bytes, return a new Handle to represent the content."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(bytes(self._ffi.buffer(bytes_ptr, bytes_len)))

    @_extern_decl("Handle", ["ExternContext*", "uint8_t*", "uint64_t"])
    def extern_store_utf8(self, context_handle, utf8_ptr, utf8_len):
        """Given a context and UTF8 bytes, return a new Handle to represent the content."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(self._ffi.string(utf8_ptr, utf8_len).decode())

    @_extern_decl("Handle", ["ExternContext*", "uint64_t"])
    def extern_store_u64(self, context_handle, u64):
        """Given a context and uint64_t, return a new Handle to represent the uint64_t."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(u64)

    @_extern_decl("Handle", ["ExternContext*", "int64_t"])
    def extern_store_i64(self, context_handle, i64):
        """Given a context and int64_t, return a new Handle to represent the int64_t."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(i64)

    @_extern_decl("Handle", ["ExternContext*", "double"])
    def extern_store_f64(self, context_handle, f64):
        """Given a context and double, return a new Handle to represent the double."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(f64)

    @_extern_decl("Handle", ["ExternContext*", "_Bool"])
    def extern_store_bool(self, context_handle, b):
        """Given a context and _Bool, return a new Handle to represent the _Bool."""
        c = self._ffi.from_handle(context_handle)
        return c.to_value(b)

    @_extern_decl("Handle", ["ExternContext*", "Handle*", "uint8_t*", "uint64_t"])
    def extern_project_ignoring_type(self, context_handle, val, field_str_ptr, field_str_len):
        """Given a Handle for `obj`, and a field name, project the field as a new Handle."""
        c = self._ffi.from_handle(context_handle)
        obj = c.from_value(val[0])
        field_name = self.to_py_str(field_str_ptr, field_str_len)
        projected = getattr(obj, field_name)

        return c.to_value(projected)

    @_extern_decl("HandleBuffer", ["ExternContext*", "Handle*", "uint8_t*", "uint64_t"])
    def extern_project_multi(self, context_handle, val, field_str_ptr, field_str_len):
        """Given a Key for `obj`, and a field name, project the field as a list of Keys."""
        c = self._ffi.from_handle(context_handle)
        obj = c.from_value(val[0])
        field_name = self.to_py_str(field_str_ptr, field_str_len)

        return c.vals_buf(tuple(c.to_value(p) for p in getattr(obj, field_name)))

    @_extern_decl("Handle", ["ExternContext*", "uint8_t*", "uint64_t"])
    def extern_create_exception(self, context_handle, msg_ptr, msg_len):
        """Given a utf8 message string, create an Exception object."""
        c = self._ffi.from_handle(context_handle)
        msg = self.to_py_str(msg_ptr, msg_len)
        return c.to_value(Exception(msg))

    @_extern_decl("PyGeneratorResponse", ["ExternContext*", "Handle*", "Handle*"])
    def extern_generator_send(self, context_handle, func, arg):
        """Given a generator, send it the given value and return a response."""
        c = self._ffi.from_handle(context_handle)
        response = self._ffi.new("PyGeneratorResponse*")
        try:
            res = c.from_value(func[0]).send(c.from_value(arg[0]))

            if isinstance(res, Get):
                # Get.
                response.tag = self._lib.Get
                response.get = (
                    TypeId(c.to_id(res.product)),
                    c.to_value(res.subject),
                    c.identify(res.subject),
                    TypeId(c.to_id(res.subject_declared_type)),
                )
            elif type(res) in (tuple, list):
                # GetMulti.
                response.tag = self._lib.GetMulti
                response.get_multi = (
                    c.type_ids_buf([TypeId(c.to_id(g.product)) for g in res]),
                    c.vals_buf([c.to_value(g.subject) for g in res]),
                    c.identities_buf([c.identify(g.subject) for g in res]),
                )
            else:
                raise ValueError(f"internal engine error: unrecognized coroutine result {res}")
        except StopIteration as e:
            if not e.args:
                raise
            # This was a `return` from a coroutine, as opposed to a `StopIteration` raised
            # by calling `next()` on an empty iterator.
            response.tag = self._lib.Broke
            response.broke = (c.to_value(e.value),)
        except Exception as e:
            # Throw.
            response.tag = self._lib.Throw
            val = e
            val._formatted_exc = traceback.format_exc()
            response.throw = (c.to_value(val),)

        return response[0]

    @_extern_decl("PyResult", ["ExternContext*", "Handle*", "Handle**", "uint64_t"])
    def extern_call(self, context_handle, func, args_ptr, args_len):
        """Given a callable, call it."""
        c = self._ffi.from_handle(context_handle)
        runnable = c.from_value(func[0])
        args = tuple(c.from_value(arg[0]) for arg in self._ffi.unpack(args_ptr, args_len))
        return self.call(c, runnable, args)


class TypeId(NamedTuple):
    """Corresponds to the native object of the same name."""

    tup_0: Any


class Key(NamedTuple):
    """Corresponds to the native object of the same name."""

    tup_0: Any
    type_id: TypeId


class Function(NamedTuple):
    """Corresponds to the native object of the same name."""

    key: Key


class EngineTypes(NamedTuple):
    """Python types that need to be passed to the engine.

    N.B. EngineTypes needs to correspond field-by-field to the Types struct defined in
    `src/rust/engine/src/types.rs` in order to avoid breakage (field definition order matters, not
    just the names of fields!).
    """

    construct_directory_digest: Function
    directory_digest: TypeId
    construct_snapshot: Function
    snapshot: TypeId
    construct_file_content: Function
    construct_files_content: Function
    files_content: TypeId
    construct_process_result: Function
    construct_materialize_directories_results: Function
    construct_materialize_directory_result: Function
    address: TypeId
    path_globs: TypeId
    directories_to_merge: TypeId
    directory_with_prefix_to_strip: TypeId
    directory_with_prefix_to_add: TypeId
    input_files_content: TypeId
    dir: TypeId
    file: TypeId
    link: TypeId
    platform: TypeId
    multi_platform_process: TypeId
    process_result: TypeId
    coroutine: TypeId
    url_to_fetch: TypeId
    string: TypeId
    bytes: TypeId
    construct_interactive_process_result: Function
    interactive_process: TypeId
    interactive_process_result: TypeId
    snapshot_subset: TypeId
    construct_platform: Function


class PyResult(NamedTuple):
    """Corresponds to the native object of the same name."""

    is_throw: bool
    handle: Any


class RawResult(NamedTuple):
    """Corresponds to the native object of the same name."""

    is_throw: bool
    handle: Any
    raw_pointer: Any


class ExternContext:
    """A wrapper around python objects used in static extern functions in this module.

    See comments in `src/rust/engine/src/interning.rs` for more information on the relationship
    between `Key`s and `Handle`s.
    """

    def __init__(self, ffi, lib):
        """
    :param CompiledCFFI ffi: The CFFI handle to the compiled native engine lib.
    """
        self._ffi = ffi
        self._lib = lib

        # A handle to this object to ensure that the native wrapper survives at least as
        # long as this object.
        self._handle = self._ffi.new_handle(self)

        # A lookup table for `id(type) -> types`.
        self._types = {}

        # Outstanding FFI object handles.
        self._handles = set()

    def buf(self, bytestring):
        buf = self._ffi.new("uint8_t[]", bytestring)
        return (buf, len(bytestring), self.to_value(buf))

    def utf8_buf(self, string):
        return self.buf(string.encode())

    def utf8_buf_buf(self, strings):
        bufs = [self.utf8_buf(string) for string in strings]
        buf_buf = self._ffi.new("Buffer[]", bufs)
        return (buf_buf, len(bufs), self.to_value(buf_buf))

    def utf8_dict(self, d):
        """Stores the dict as a list of interleaved keys and values, as utf8 strings."""
        bufs = [self.utf8_buf(item) for keyvalue in d.items() for item in keyvalue]
        buf_buf = self._ffi.new("Buffer[]", bufs)
        return (buf_buf, len(bufs), self.to_value(buf_buf))

    def vals_buf(self, vals):
        buf = self._ffi.new("Handle[]", vals)
        return (buf, len(vals), self.to_value(buf))

    def identities_buf(self, idents):
        buf = self._ffi.new("Ident[]", idents)
        return (buf, len(idents), self.to_value(buf))

    def type_ids_buf(self, types):
        buf = self._ffi.new("TypeId[]", types)
        return (buf, len(types), self.to_value(buf))

    def to_value(self, obj):
        handle = self._ffi.new_handle(obj)
        self._handles.add(handle)
        return handle

    def from_value(self, val):
        return self._ffi.from_handle(val)

    def raise_or_return(self, pyresult):
        """Consumes the given PyResult to raise/return the exception/value it represents."""
        value = self.from_value(pyresult.handle)
        self._handles.remove(pyresult.handle)
        if pyresult.is_throw:
            raise value
        else:
            return value

    def drop_handles(self, handles):
        self._handles -= set(handles)

    def identify(self, obj):
        """Return an Ident-shaped tuple for the given object."""
        try:
            hash_ = hash(obj)
        except TypeError as e:
            raise TypeError(f"failed to hash object {obj}: {e}") from e
        type_id = self.to_id(type(obj))
        return (hash_, TypeId(type_id))

    def to_id(self, typ):
        type_id = id(typ)
        self._types[type_id] = typ
        return type_id

    def from_id(self, type_id):
        return self._types[type_id]

    def to_key(self, obj):
        cdata = self._lib.key_for(self.to_value(obj))
        return Key(cdata.id_, TypeId(cdata.type_id.tup_0))

    def from_key(self, key):
        return self._lib.val_for(key)


class Native(metaclass=SingletonMetaclass):
    """Encapsulates fetching a platform specific version of the native portion of the engine."""

    _errors_during_execution = None

    class CFFIExternMethodRuntimeErrorInfo(NamedTuple):
        """Encapsulates an exception raised when a CFFI extern is called so that it can be
        displayed.

        When an exception is raised in the body of a CFFI extern, the `onerror` handler is used to
        capture it, storing the exception info as an instance of `CFFIExternMethodRuntimeErrorInfo` with
        `.add_cffi_extern_method_runtime_exception()`. The scheduler will then check whether any
        exceptions were stored by calling `.consume_cffi_extern_method_runtime_exceptions()` after
        specific calls to the native library which may raise.

        Note that `.consume_cffi_extern_method_runtime_exceptions()` will also clear out all stored
        exceptions, so exceptions should be stored separately after consumption.

        Some ways that exceptions in CFFI extern methods can be handled are described in
        https://cffi.readthedocs.io/en/latest/using.html#extern-python-reference.
        """

        exc_type: Type
        exc_value: BaseException
        traceback: Any

    def reset_cffi_extern_method_runtime_exceptions(self):
        self._errors_during_execution = []

    def _peek_cffi_extern_method_runtime_exceptions(self):
        return self._errors_during_execution

    def consume_cffi_extern_method_runtime_exceptions(self):
        res = self._peek_cffi_extern_method_runtime_exceptions()
        self.reset_cffi_extern_method_runtime_exceptions()
        return res

    def add_cffi_extern_method_runtime_exception(self, error_info):
        assert isinstance(error_info, self.CFFIExternMethodRuntimeErrorInfo)
        self._errors_during_execution.append(error_info)

    class BinaryLocationError(Exception):
        pass

    @memoized_property
    def binary(self):
        """Load and return the path to the native engine binary."""
        lib_name = "{}.so".format(NATIVE_ENGINE_MODULE)
        lib_path = os.path.join(safe_mkdtemp(), lib_name)
        try:
            with closing(pkg_resources.resource_stream(__name__, lib_name)) as input_fp:
                # NB: The header stripping code here must be coordinated with header insertion code in
                #     build-support/bin/native/bootstrap_code.sh
                engine_version = input_fp.readline().decode().strip()
                repo_version = input_fp.readline().decode().strip()
                logger.debug("using {} built at {}".format(engine_version, repo_version))
                with open(lib_path, "wb") as output_fp:
                    output_fp.write(input_fp.read())
        except (IOError, OSError) as e:
            raise self.BinaryLocationError(
                "Error unpacking the native engine binary to path {}: {}".format(lib_path, e), e
            )
        return lib_path

    @memoized_property
    def lib(self):
        """Load and return the native engine module."""
        lib = self.ffi.dlopen(self.binary)
        _FFISpecification(self.ffi, lib).register_cffi_externs(self)
        return lib

    @memoized_property
    def ffi(self):
        """A CompiledCFFI handle as imported from the native engine python module."""
        return getattr(self._ffi_module, "ffi")

    @memoized_property
    def ffi_lib(self):
        """A CFFI Library handle as imported from the native engine python module."""
        return getattr(self._ffi_module, "lib")

    @memoized_property
    def _ffi_module(self):
        """Load the native engine as a python module and register CFFI externs."""
        native_bin_dir = os.path.dirname(self.binary)
        logger.debug("loading native engine python module from: %s", native_bin_dir)
        sys.path.insert(0, native_bin_dir)
        return importlib.import_module(NATIVE_ENGINE_MODULE)

    @memoized_property
    def context(self):
        # We statically initialize a ExternContext to correspond to the queue of dropped
        # Handles that the native code maintains.
        def init_externs():
            context = ExternContext(self.ffi, self.lib)
            none = self.ffi.from_handle(context._handle).to_value(None)
            self.lib.externs_set(
                context._handle,
                logger.getEffectiveLevel(),
                none,
                self.ffi_lib.extern_call,
                self.ffi_lib.extern_generator_send,
                self.ffi_lib.extern_get_type_for,
                self.ffi_lib.extern_get_handle_from_type_id,
                self.ffi_lib.extern_is_union,
                self.ffi_lib.extern_identify,
                self.ffi_lib.extern_equals,
                self.ffi_lib.extern_clone_val,
                self.ffi_lib.extern_drop_handles,
                self.ffi_lib.extern_type_to_str,
                self.ffi_lib.extern_val_to_bytes,
                self.ffi_lib.extern_val_to_str,
                self.ffi_lib.extern_store_tuple,
                self.ffi_lib.extern_store_set,
                self.ffi_lib.extern_store_dict,
                self.ffi_lib.extern_store_bytes,
                self.ffi_lib.extern_store_utf8,
                self.ffi_lib.extern_store_u64,
                self.ffi_lib.extern_store_i64,
                self.ffi_lib.extern_store_f64,
                self.ffi_lib.extern_store_bool,
                self.ffi_lib.extern_project_ignoring_type,
                self.ffi_lib.extern_project_multi,
                self.ffi_lib.extern_val_to_bool,
                self.ffi_lib.extern_create_exception,
            )
            return context

        return self.ffi.init_once(init_externs, "ExternContext singleton")

    def new(self, cdecl, init):
        return self.ffi.new(cdecl, init)

    def gc(self, cdata, destructor):
        """Register a method to be called when `cdata` is garbage collected.

        Returns a new reference that should be used in place of `cdata`.
        """
        return self.ffi.gc(cdata, destructor)

    def unpack(self, cdata_ptr, count):
        """Given a pointer representing an array, and its count of entries, return a list."""
        return self.ffi.unpack(cdata_ptr, count)

    def buffer(self, cdata):
        return self.ffi.buffer(cdata)

    def to_ids_buf(self, types):
        return self.context.type_ids_buf([TypeId(self.context.to_id(t)) for t in types])

    def decompress_tarball(self, tarfile_path, dest_dir):
        result = self.lib.decompress_tarball(tarfile_path, dest_dir)
        return self.context.raise_or_return(result)

    def init_rust_logging(self, level, log_show_rust_3rdparty):
        return self.lib.init_logging(level, log_show_rust_3rdparty)

    def setup_pantsd_logger(self, log_file_path, level):
        log_file_path = log_file_path.encode()
        result = self.lib.setup_pantsd_logger(log_file_path, level)
        return self.context.raise_or_return(result)

    def setup_stderr_logger(self, level):
        return self.lib.setup_stderr_logger(level)

    def write_log(self, msg, level, target):
        msg = msg.encode()
        target = target.encode()
        return self.lib.write_log(msg, level, target)

    def write_stdout(self, session, msg: str):
        return self.lib.write_stdout(session, msg.encode())

    def write_stderr(self, session, msg: str):
        return self.lib.write_stdout(session, msg.encode())

    def flush_log(self):
        return self.lib.flush_log()

    def override_thread_logging_destination_to_just_pantsd(self):
        self.lib.override_thread_logging_destination(self.lib.Pantsd)

    def override_thread_logging_destination_to_just_stderr(self):
        self.lib.override_thread_logging_destination(self.lib.Stderr)

    def match_path_globs(self, path_globs: PathGlobs, paths: Iterable[str]) -> bool:
        path_globs = self.context.to_value(path_globs)
        paths_buf = self.context.utf8_buf_buf(tuple(paths))
        result = self.lib.match_path_globs(path_globs, paths_buf)
        return cast(bool, self.context.raise_or_return(result))

    def new_tasks(self):
        return self.gc(self.lib.tasks_create(), self.lib.tasks_destroy)

    def new_execution_request(self):
        return self.gc(self.lib.execution_request_create(), self.lib.execution_request_destroy)

    def new_session(
        self,
        scheduler,
        should_record_zipkin_spans,
        should_render_ui,
        ui_worker_count,
        build_id,
        should_report_workunits: bool,
    ):
        return self.gc(
            self.lib.session_create(
                scheduler,
                should_record_zipkin_spans,
                should_render_ui,
                ui_worker_count,
                self.context.utf8_buf(build_id),
                should_report_workunits,
            ),
            self.lib.session_destroy,
        )

    def new_scheduler(
        self,
        tasks,
        root_subject_types,
        build_root,
        local_store_dir,
        ignore_patterns: List[str],
        use_gitignore: bool,
        execution_options,
    ):
        """Create and return an ExternContext and native Scheduler."""

        def func(fn):
            return Function(self.context.to_key(fn))

        def ti(type_obj):
            return TypeId(self.context.to_id(type_obj))

        engine_types = EngineTypes(
            construct_directory_digest=func(Digest),
            directory_digest=ti(Digest),
            construct_snapshot=func(Snapshot),
            snapshot=ti(Snapshot),
            construct_file_content=func(FileContent),
            construct_files_content=func(FilesContent),
            files_content=ti(FilesContent),
            construct_process_result=func(FallibleProcessResultWithPlatform),
            construct_materialize_directories_results=func(MaterializeDirectoriesResult),
            construct_materialize_directory_result=func(MaterializeDirectoryResult),
            address=ti(Address),
            path_globs=ti(PathGlobs),
            directories_to_merge=ti(DirectoriesToMerge),
            directory_with_prefix_to_strip=ti(DirectoryWithPrefixToStrip),
            directory_with_prefix_to_add=ti(DirectoryWithPrefixToAdd),
            input_files_content=ti(InputFilesContent),
            dir=ti(Dir),
            file=ti(File),
            link=ti(Link),
            platform=ti(Platform),
            multi_platform_process=ti(MultiPlatformProcess),
            process_result=ti(FallibleProcessResultWithPlatform),
            coroutine=ti(CoroutineType),
            url_to_fetch=ti(UrlToFetch),
            string=ti(str),
            bytes=ti(bytes),
            construct_interactive_process_result=func(InteractiveProcessResult),
            interactive_process=ti(InteractiveProcessRequest),
            interactive_process_result=ti(InteractiveProcessResult),
            snapshot_subset=ti(SnapshotSubset),
            construct_platform=func(Platform),
        )

        scheduler_result = self.lib.scheduler_create(
            tasks,
            engine_types,
            # Project tree.
            self.context.utf8_buf(build_root),
            self.context.utf8_buf(local_store_dir),
            self.context.utf8_buf_buf(ignore_patterns),
            use_gitignore,
            self.to_ids_buf(root_subject_types),
            # Remote execution config.
            execution_options.remote_execution,
            self.context.utf8_buf_buf(execution_options.remote_store_server),
            # We can't currently pass Options to the rust side, so we pass empty strings for None.
            self.context.utf8_buf(execution_options.remote_execution_server or ""),
            self.context.utf8_buf(execution_options.remote_execution_process_cache_namespace or ""),
            self.context.utf8_buf(execution_options.remote_instance_name or ""),
            self.context.utf8_buf(execution_options.remote_ca_certs_path or ""),
            self.context.utf8_buf(execution_options.remote_oauth_bearer_token_path or ""),
            execution_options.remote_store_thread_count,
            execution_options.remote_store_chunk_bytes,
            execution_options.remote_store_connection_limit,
            execution_options.remote_store_chunk_upload_timeout_seconds,
            execution_options.remote_store_rpc_retries,
            self.context.utf8_buf_buf(execution_options.remote_execution_extra_platform_properties),
            execution_options.process_execution_local_parallelism,
            execution_options.process_execution_remote_parallelism,
            execution_options.process_execution_cleanup_local_dirs,
            execution_options.process_execution_speculation_delay,
            self.context.utf8_buf(execution_options.process_execution_speculation_strategy),
            execution_options.process_execution_use_local_cache,
            self.context.utf8_dict(execution_options.remote_execution_headers),
            execution_options.process_execution_local_enable_nailgun,
            execution_options.experimental_fs_watcher,
        )
        if scheduler_result.is_throw:
            value = self.context.from_value(scheduler_result.throw_handle)
            self.context.drop_handles([scheduler_result.throw_handle])
            raise value
        else:
            scheduler = scheduler_result.raw_pointer
        return self.gc(scheduler, self.lib.scheduler_destroy)

    def set_panic_handler(self):
        if os.getenv("RUST_BACKTRACE", "0") == "0":
            # The panic handler hides a lot of rust tracing which may be useful.
            # Don't activate it when the user explicitly asks for rust backtraces.
            self.lib.set_panic_handler()
