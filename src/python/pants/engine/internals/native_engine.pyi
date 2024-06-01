# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from io import RawIOBase
from typing import (
    Any,
    Callable,
    ClassVar,
    FrozenSet,
    Generic,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    TextIO,
    Tuple,
    TypeVar,
    overload,
)

from typing_extensions import Self

from pants.engine.fs import (
    CreateDigest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    NativeDownloadFile,
    PathGlobs,
    Paths,
)
from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.internals.native_dep_inference import (
    NativeParsedJavascriptDependencies,
    NativeParsedPythonDependencies,
)
from pants.engine.internals.scheduler import Workunit, _PathGlobsAndRootCollection
from pants.engine.internals.session import RunId, SessionValues
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    Process,
)

# TODO: black and flake8 disagree about the content of this file:
#   see https://github.com/psf/black/issues/1548
# flake8: noqa: E302

# ------------------------------------------------------------------------------
# (core)
# ------------------------------------------------------------------------------

class PyFailure:
    def get_error(self) -> Exception | None: ...

# ------------------------------------------------------------------------------
# Address
# ------------------------------------------------------------------------------

BANNED_CHARS_IN_TARGET_NAME: FrozenSet
BANNED_CHARS_IN_GENERATED_NAME: FrozenSet
BANNED_CHARS_IN_PARAMETERS: FrozenSet

def address_spec_parse(
    spec: str,
) -> tuple[tuple[str, str | None, str | None, tuple[tuple[str, str], ...]], str | None]: ...

class AddressParseException(Exception):
    pass

class InvalidAddressError(Exception):
    pass

class InvalidSpecPathError(Exception):
    pass

class InvalidTargetNameError(Exception):
    pass

class InvalidParametersError(Exception):
    pass

class UnsupportedWildcardError(Exception):
    pass

class AddressInput:
    """A string that has been parsed and normalized using the Address syntax.

    An AddressInput must be resolved into an Address using the engine (which involves inspecting
    disk to determine the types of its path component).
    """

    def __init__(
        self,
        original_spec: str,
        path_component: str,
        description_of_origin: str,
        target_component: str | None = None,
        generated_component: str | None = None,
        parameters: Mapping[str, str] | None = None,
    ) -> None: ...
    @classmethod
    def parse(
        cls,
        spec: str,
        *,
        description_of_origin: str,
        relative_to: str | None = None,
        subproject_roots: Sequence[str] | None = None,
    ) -> Self:
        """Parse a string into an AddressInput.

        :param spec: Target address spec.
        :param relative_to: path to use for sibling specs, ie: ':another_in_same_build_family',
          interprets the missing spec_path part as `relative_to`.
        :param subproject_roots: Paths that correspond with embedded build roots under
          the current build root.
        :param description_of_origin: where the AddressInput comes from, e.g. "CLI arguments" or
          "the option `--paths-from`". This is used for better error messages.

        For example:

            some_target(
                name='mytarget',
                dependencies=['path/to/buildfile:targetname'],
            )

        Where `path/to/buildfile:targetname` is the dependent target address spec.

        In there is no target name component, it defaults the default target in the resulting
        Address's spec_path.

        Optionally, specs can be prefixed with '//' to denote an absolute spec path. This is
        normally not significant except when a spec referring to a root level target is needed
        from deeper in the tree. For example, in `path/to/buildfile/BUILD`:

            some_target(
                name='mytarget',
                dependencies=[':targetname'],
            )

        The `targetname` spec refers to a target defined in `path/to/buildfile/BUILD*`. If instead
        you want to reference `targetname` in a root level BUILD file, use the absolute form.
        For example:

            some_target(
                name='mytarget',
                dependencies=['//:targetname'],
            )

        The spec may be for a generated target: `dir:generator#generated`.

        The spec may be a file, such as `a/b/c.txt`. It may include a relative address spec at the
        end, such as `a/b/c.txt:original` or `a/b/c.txt:../original`, to disambiguate which target
        the file comes from; otherwise, it will be assumed to come from the default target in the
        directory, i.e. a target which leaves off `name`.
        """
        ...
    @property
    def spec(self) -> str: ...
    @property
    def path_component(self) -> str: ...
    @property
    def target_component(self) -> str | None: ...
    @property
    def generated_component(self) -> str | None: ...
    @property
    def parameters(self) -> dict[str, str]: ...
    @property
    def description_of_origin(self) -> str: ...
    def file_to_address(self) -> Address:
        """Converts to an Address by assuming that the path_component is a file on disk."""
        ...
    def dir_to_address(self) -> Address:
        """Converts to an Address by assuming that the path_component is a directory on disk."""
        ...

class Address:
    """The unique address for a `Target`.

    Targets explicitly declared in BUILD files use the format `path/to:tgt`, whereas targets
    generated from other targets use the format `path/to:generator#generated`.
    """

    def __init__(
        self,
        spec_path: str,
        *,
        target_name: str | None = None,
        parameters: Mapping[str, str] | None = None,
        generated_name: str | None = None,
        relative_file_path: str | None = None,
    ) -> None:
        """
        :param spec_path: The path from the build root to the directory containing the BUILD file
          for the target. If the target is generated, this is the path to the generator target.
        :param target_name: The name of the target. For generated targets, this is the name of
            its target generator. If the `name` is left off (i.e. the default), set to `None`.
        :param parameters: A series of key-value pairs which are incorporated into the identity of
            the Address.
        :param generated_name: The name of what is generated. You can use a file path if the
            generated target represents an entity from the file system, such as `a/b/c` or
            `subdir/f.ext`.
        :param relative_file_path: The relative path from the spec_path to an addressed file,
          if any. Because files must always be located below targets that apply metadata to
          them, this will always be relative.
        """
        ...
    @property
    def spec_path(self) -> str: ...
    @property
    def generated_name(self) -> str | None: ...
    @property
    def relative_file_path(self) -> str | None: ...
    @property
    def parameters(self) -> dict[str, str]: ...
    @property
    def is_generated_target(self) -> bool: ...
    @property
    def is_file_target(self) -> bool: ...
    @property
    def is_parametrized(self) -> bool: ...
    def is_parametrized_subset_of(self, other: Address) -> bool:
        """True if this Address is == to the given Address, but with a subset of its parameters."""
        ...
    @property
    def filename(self) -> str: ...
    @property
    def target_name(self) -> str: ...
    @property
    def parameters_repr(self) -> str: ...
    @property
    def spec(self) -> str:
        """The canonical string representation of the Address.

        Prepends '//' if the target is at the root, to disambiguate build root level targets from
        "relative" spec notation.
        """
        ...
    @property
    def path_safe_spec(self) -> str: ...
    def parametrize(self, parameters: Mapping[str, str], replace: bool = False) -> Address:
        """Creates a new Address with the given `parameters` merged or replaced over
        self.parameters."""
        ...
    def maybe_convert_to_target_generator(self) -> Address:
        """If this address is generated or parametrized, convert it to its generator target.

        Otherwise, return self unmodified.
        """
        ...
    def create_generated(self, generated_name: str) -> Address: ...
    def create_file(self, relative_file_path: str) -> Address: ...
    def debug_hint(self) -> str: ...
    def metadata(self) -> dict[str, Any]: ...

    # NB: These methods are provided by our `__richcmp__` implementation, but must be declared in
    # the stub in order for mypy to accept them as comparable.
    def __lt__(self, other: Any) -> bool: ...
    def __gt__(self, other: Any) -> bool: ...

# ------------------------------------------------------------------------------
# Scheduler
# ------------------------------------------------------------------------------

class PyExecutor:
    def __init__(self, core_threads: int, max_threads: int) -> None: ...
    def to_borrowed(self) -> PyExecutor: ...
    def shutdown(self, duration_secs: float) -> None: ...

# ------------------------------------------------------------------------------
# Target
# ------------------------------------------------------------------------------

# Type alias to express the intent that the type should be immutable and hashable. There's nothing
# to actually enforce this, outside of convention.
ImmutableValue = Any

class _NoValue:
    def __bool__(self) -> bool:
        """NB: Always returns `False`."""
        ...
    def __repr__(self) -> str: ...

# Marker for unspecified field values that should use the default value if applicable.
NO_VALUE: _NoValue

class Field:
    """A Field.

    The majority of fields should use field templates like `BoolField`, `StringField`, and
    `StringSequenceField`. These subclasses will provide sensible type hints and validation
    automatically.

    If you are directly subclassing `Field`, you should likely override `compute_value()`
    to perform any custom hydration and/or validation, such as converting unhashable types to
    hashable types or checking for banned values. The returned value must be hashable
    (and should be immutable) so that this Field may be used by the engine. This means, for
    example, using tuples rather than lists and using `FrozenOrderedSet` rather than `set`.

    If you plan to use the engine to fully hydrate the value, you can also inherit
    `AsyncFieldMixin`, which will store an `address: Address` property on the `Field` instance.

    Subclasses should also override the type hints for `value` and `raw_value` to be more precise
    than `Any`. The type hint for `raw_value` is used to generate documentation, e.g. for
    `./pants help $target_type`.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.

    Example:

        # NB: Really, this should subclass IntField. We only use Field as an example.
        class Timeout(Field):
            alias = "timeout"
            value: Optional[int]
            default = None
            help = "A timeout field.\n\nMore information."

            @classmethod
            def compute_value(cls, raw_value: Optional[int], address: Address) -> Optional[int]:
                value_or_default = super().compute_value(raw_value, address=address)
                if value_or_default is not None and not isinstance(value_or_default, int):
                    raise ValueError(
                        "The `timeout` field expects an integer, but was given"
                        f"{value_or_default} for target {address}."
                    )
                return value_or_default
    """

    # Opt-in per field class to use a "no value" marker for the `raw_value` in `compute_value()` in
    # case the field was not represented in the BUILD file.
    #
    # This will allow users to provide `None` as the field value (when applicable) without getting
    # the fields default value.
    none_is_valid_value: ClassVar[bool] = False

    # Subclasses must define these.
    alias: ClassVar[str]
    help: ClassVar[str | Callable[[], str]]

    # Subclasses must define at least one of these two.
    default: ClassVar[ImmutableValue]
    required: ClassVar[bool] = False

    # Subclasses may define these.
    removal_version: ClassVar[str | None] = None
    removal_hint: ClassVar[str | None] = None

    deprecated_alias: ClassVar[str | None] = None
    deprecated_alias_removal_version: ClassVar[str | None] = None

    value: ImmutableValue | None

    def __init__(self, raw_value: Any | None, address: Address) -> None: ...
    @classmethod
    def compute_value(cls, raw_value: Any | None, address: Address) -> ImmutableValue:
        """Convert the `raw_value` into `self.value`.

        You should perform any optional validation and/or hydration here. For example, you may want
        to check that an integer is > 0 or convert an `Iterable[str]` to `List[str]`.

        The resulting value must be hashable (and should be immutable).
        """
        ...

# ------------------------------------------------------------------------------
# FS
# ------------------------------------------------------------------------------

class Digest:
    """A Digest is a lightweight reference to a set of files known about by the engine.

    You can use `await Get(Snapshot, Digest)` to see the file names referred to, or use `await
    Get(DigestContents, Digest)` to see the actual file content.
    """

    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...
    def __eq__(self, other: Digest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class FileDigest:
    """A FileDigest is a digest that refers to a file's content, without its name."""

    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...
    def __eq__(self, other: FileDigest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class Snapshot:
    """A Snapshot is a collection of sorted file paths and dir paths fingerprinted by their
    names/content.

    You can lift a `Digest` to a `Snapshot` with `await Get(Snapshot, Digest, my_digest)`.

    The `files` and `dirs` properties are symlink oblivious. If you require knowing about symlinks,
    you can use the `digest` property to request the `DigestEntries`:
    `await Get(DigestEntries, Digest, snapshot.digest)`.
    """

    @classmethod
    def create_for_testing(cls, files: Sequence[str], dirs: Sequence[str]) -> Snapshot: ...
    @property
    def digest(self) -> Digest: ...
    @property
    def dirs(self) -> tuple[str, ...]: ...
    @property
    def files(self) -> tuple[str, ...]: ...
    # Don't call this, call pants.engine.fs.SnapshotDiff instead
    def _diff(
        self, other: Snapshot
    ) -> tuple[
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]: ...
    def __eq__(self, other: Snapshot | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class MergeDigests:
    """A request to merge several digests into one single digest.

    This will fail if there are any conflicting changes, such as two digests having the same
    file but with different content.

    Example:

        result = await Get(Digest, MergeDigests([digest1, digest2])
    """

    def __init__(self, digests: Iterable[Digest]) -> None: ...
    def __eq__(self, other: MergeDigests | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class AddPrefix:
    """A request to add the specified prefix path to every file and directory in the digest.

    Example:

        result = await Get(Digest, AddPrefix(input_digest, "my_dir")
    """

    def __init__(self, digest: Digest, prefix: str) -> None: ...
    def __eq__(self, other: AddPrefix | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class RemovePrefix:
    """A request to remove the specified prefix path from every file and directory in the digest.

    This will fail if there are any files or directories in the original input digest without the
    specified prefix.

    Example:

        result = await Get(Digest, RemovePrefix(input_digest, "my_dir")
    """

    def __init__(self, digest: Digest, prefix: str) -> None: ...
    def __eq__(self, other: RemovePrefix | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class FilespecMatcher:
    def __init__(self, includes: Sequence[str], excludes: Sequence[str]) -> None: ...
    def __eq__(self, other: FilespecMatcher | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
    def matches(self, paths: Sequence[str]) -> list[str]: ...

EMPTY_DIGEST: Digest
EMPTY_FILE_DIGEST: FileDigest
EMPTY_SNAPSHOT: Snapshot

def default_cache_path() -> str: ...

# ------------------------------------------------------------------------------
# Intrinsics
# ------------------------------------------------------------------------------

async def create_digest_to_digest(
    create_digest: CreateDigest,
) -> Digest: ...
async def path_globs_to_digest(
    path_globs: PathGlobs,
) -> Digest: ...
async def path_globs_to_paths(
    path_globs: PathGlobs,
) -> Paths: ...
async def download_file_to_digest(
    native_download_file: NativeDownloadFile,
) -> Digest: ...
async def digest_to_snapshot(digest: Digest) -> Snapshot: ...
async def directory_digest_to_digest_contents(digest: Digest) -> DigestContents: ...
async def directory_digest_to_digest_entries(digest: Digest) -> DigestEntries: ...
async def merge_digests_request_to_digest(merge_digests: MergeDigests) -> Digest: ...
async def remove_prefix_request_to_digest(remove_prefix: RemovePrefix) -> Digest: ...
async def add_prefix_request_to_digest(add_prefix: AddPrefix) -> Digest: ...
async def process_request_to_process_result(
    process: Process, process_execution_environment: ProcessExecutionEnvironment
) -> FallibleProcessResult: ...
async def digest_subset_to_digest(digest_subset: DigestSubset) -> Digest: ...
async def session_values() -> SessionValues: ...
async def run_id() -> RunId: ...
async def interactive_process(
    process: InteractiveProcess, process_execution_environment: ProcessExecutionEnvironment
) -> InteractiveProcessResult: ...
async def docker_resolve_image(request: DockerResolveImageRequest) -> DockerResolveImageResult: ...
async def parse_python_deps(
    deps_request: NativeDependenciesRequest,
) -> NativeParsedPythonDependencies: ...
async def parse_javascript_deps(
    deps_request: NativeDependenciesRequest,
) -> NativeParsedJavascriptDependencies: ...

# ------------------------------------------------------------------------------
# `pantsd`
# ------------------------------------------------------------------------------

def pantsd_fingerprint_compute(expected_option_names: set[str]) -> str: ...

# ------------------------------------------------------------------------------
# Process
# ------------------------------------------------------------------------------

class ProcessExecutionEnvironment:
    """Settings from the current Environment for how a `Process` should be run.

    Note that most values from the Environment are instead set via changing the arguments `argv` and
    `env` in the `Process` constructor.
    """

    def __init__(
        self,
        *,
        environment_name: str | None,
        platform: str,
        docker_image: str | None,
        remote_execution: bool,
        remote_execution_extra_platform_properties: Sequence[tuple[str, str]],
        execute_in_workspace: bool,
    ) -> None: ...
    def __eq__(self, other: ProcessExecutionEnvironment | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
    @property
    def name(self) -> str | None: ...
    @property
    def environment_type(self) -> str: ...
    @property
    def remote_execution(self) -> bool: ...
    @property
    def docker_image(self) -> str | None: ...
    @property
    def platform(self) -> str: ...
    @property
    def remote_execution_extra_platform_properties(self) -> list[tuple[str, str]]: ...

# ------------------------------------------------------------------------------
# Workunits
# ------------------------------------------------------------------------------

def all_counter_names() -> list[str]: ...

# ------------------------------------------------------------------------------
# Nailgun
# ------------------------------------------------------------------------------

class PyNailgunClient:
    def __init__(self, port: int, executor: PyExecutor) -> None: ...
    def execute(self, command: str, args: list[str], env: dict[str, str]) -> int: ...

class PantsdConnectionException(Exception):
    pass

class PantsdClientException(Exception):
    pass

# ------------------------------------------------------------------------------
# Options
# ------------------------------------------------------------------------------

class PyOptionId:
    def __init__(
        self, *components: str, scope: str | None = None, switch: str | None = None
    ) -> None: ...

class PyConfigSource:
    def __init__(self, path: str, content: bytes) -> None: ...

T = TypeVar("T")
# A pair of (option value, rank). See src/python/pants/option/ranked_value.py.
OptionValue = Tuple[Optional[T], int]
OptionListValue = Tuple[list[T], int]
OptionDictValue = Tuple[dict[str, Any], int]

class PyOptionParser:
    def __init__(
        self,
        args: Optional[Sequence[str]],
        env: dict[str, str],
        configs: Optional[Sequence[PyConfigSource]],
        allow_pantsrc: bool,
    ) -> None: ...
    def get_bool(self, option_id: PyOptionId, default: Optional[bool]) -> OptionValue[bool]: ...
    def get_int(self, option_id: PyOptionId, default: Optional[int]) -> OptionValue[int]: ...
    def get_float(self, option_id: PyOptionId, default: Optional[float]) -> OptionValue[float]: ...
    def get_string(self, option_id: PyOptionId, default: Optional[str]) -> OptionValue[str]: ...
    def get_bool_list(
        self, option_id: PyOptionId, default: list[bool]
    ) -> OptionListValue[bool]: ...
    def get_int_list(self, option_id: PyOptionId, default: list[int]) -> OptionListValue[int]: ...
    def get_float_list(
        self, option_id: PyOptionId, default: list[float]
    ) -> OptionListValue[float]: ...
    def get_string_list(
        self, option_id: PyOptionId, default: list[str]
    ) -> OptionListValue[str]: ...
    def get_dict(self, option_id: PyOptionId, default: dict[str, Any]) -> OptionDictValue: ...
    def get_passthrough_args(self) -> Optional[list[str]]: ...

# ------------------------------------------------------------------------------
# Testutil
# ------------------------------------------------------------------------------

class PyStubCASBuilder:
    def ac_always_errors(self) -> PyStubCASBuilder: ...
    def cas_always_errors(self) -> PyStubCASBuilder: ...
    def build(self, executor: PyExecutor) -> PyStubCAS: ...

class PyStubCAS:
    @classmethod
    def builder(cls) -> PyStubCASBuilder: ...
    @property
    def address(self) -> str: ...
    def remove(self, digest: FileDigest | Digest) -> bool: ...
    def action_cache_len(self) -> int: ...

# ------------------------------------------------------------------------------
# Dependency inference
# ------------------------------------------------------------------------------

class InferenceMetadata:
    @staticmethod
    def javascript(
        package_root: str, import_patterns: dict[str, list[str]]
    ) -> InferenceMetadata: ...
    def __eq__(self, other: InferenceMetadata | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class NativeDependenciesRequest:
    """A request to parse the dependencies of a file.

    * The `digest` is expected to contain exactly one source file.
    * Depending on the implementation, a `metadata` structure
      can be passed. It will be supplied to the native parser, and
      it will be incorporated into the cache key.


    Example:
        result = await Get(NativeParsedPythonDependencies, NativeDependenciesRequest(input_digest, None)
    """

    def __init__(self, digest: Digest, metadata: InferenceMetadata | None = None) -> None: ...
    def __eq__(self, other: NativeDependenciesRequest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

# ------------------------------------------------------------------------------
# (etc.)
# ------------------------------------------------------------------------------

class RawFdRunner(Protocol):
    def __call__(
        self,
        command: str,
        args: tuple[str, ...],
        env: dict[str, str],
        working_dir: str,
        cancellation_latch: PySessionCancellationLatch,
        stdin_fileno: int,
        stdout_fileno: int,
        stderr_fileno: int,
    ) -> int: ...

def capture_snapshots(
    scheduler: PyScheduler,
    session: PySession,
    path_globs_and_root_tuple_wrapper: _PathGlobsAndRootCollection,
) -> list[Snapshot]: ...
def ensure_remote_has_recursive(
    scheduler: PyScheduler, digests: list[Digest | FileDigest]
) -> None: ...
def ensure_directory_digest_persisted(scheduler: PyScheduler, digest: Digest) -> None: ...
def single_file_digests_to_bytes(
    scheduler: PyScheduler, digests: list[FileDigest]
) -> list[bytes]: ...
def write_digest(
    scheduler: PyScheduler,
    session: PySession,
    digest: Digest,
    path_prefix: str,
    clear_paths: Sequence[str],
) -> None: ...
def write_log(msg: str, level: int, target: str) -> None: ...
def flush_log() -> None: ...
def set_per_run_log_path(path: str | None) -> None: ...
def maybe_set_panic_handler() -> None: ...
def stdio_initialize(
    level: int,
    show_rust_3rdparty_logs: bool,
    show_target: bool,
    log_levels_by_target: dict[str, int],
    literal_filters: tuple[str, ...],
    regex_filters: tuple[str, ...],
    log_file: str,
) -> tuple[RawIOBase, TextIO, TextIO]: ...
def stdio_thread_get_destination() -> PyStdioDestination: ...
def stdio_thread_set_destination(destination: PyStdioDestination) -> None: ...
def stdio_thread_console_set(stdin_fileno: int, stdout_fileno: int, stderr_fileno: int) -> None: ...
def stdio_thread_console_color_mode_set(use_color: bool) -> None: ...
def stdio_thread_console_clear() -> None: ...
def stdio_write_stdout(msg: str) -> None: ...
def stdio_write_stderr(msg: str) -> None: ...
def task_side_effected() -> None: ...
def teardown_dynamic_ui(scheduler: PyScheduler, session: PySession) -> None: ...
def tasks_task_begin(
    tasks: PyTasks,
    func: Any,
    return_type: type,
    arg_types: Sequence[tuple[str, type]],
    masked_types: Sequence[type],
    side_effecting: bool,
    engine_aware_return_type: bool,
    cacheable: bool,
    name: str,
    desc: str,
    level: int,
) -> None: ...
def tasks_task_end(tasks: PyTasks) -> None: ...
def tasks_add_call(
    tasks: PyTasks, output: type, inputs: Sequence[type], rule_id: str, explicit_args_arity: int
) -> None: ...
def tasks_add_get(tasks: PyTasks, output: type, inputs: Sequence[type]) -> None: ...
def tasks_add_get_union(
    tasks: PyTasks, output_type: type, input_types: Sequence[type], in_scope_types: Sequence[type]
) -> None: ...
def tasks_add_query(tasks: PyTasks, output_type: type, input_types: Sequence[type]) -> None: ...
def execution_add_root_select(
    scheduler: PyScheduler,
    execution_request: PyExecutionRequest,
    param_vals: Sequence,
    product: type,
) -> None: ...
def nailgun_server_await_shutdown(server: PyNailgunServer) -> None: ...
def nailgun_server_create(
    executor: PyExecutor, port: int, runner: RawFdRunner
) -> PyNailgunServer: ...
def scheduler_create(
    executor: PyExecutor,
    tasks: PyTasks,
    types: PyTypes,
    build_root: str,
    local_execution_root_dir: str,
    named_caches_dir: str,
    ignore_patterns: Sequence[str],
    use_gitignore: bool,
    watch_filesystem: bool,
    remoting_options: PyRemotingOptions,
    local_store_options: PyLocalStoreOptions,
    exec_strategy_opts: PyExecutionStrategyOptions,
    ca_certs_path: str | None,
) -> PyScheduler: ...
def scheduler_execute(
    scheduler: PyScheduler, session: PySession, execution_request: PyExecutionRequest
) -> list: ...
def scheduler_metrics(scheduler: PyScheduler, session: PySession) -> dict[str, int]: ...
def scheduler_live_items(
    scheduler: PyScheduler, session: PySession
) -> tuple[list[Any], dict[str, tuple[int, int]]]: ...
def scheduler_shutdown(scheduler: PyScheduler, timeout_secs: int) -> None: ...
def session_new_run_id(session: PySession) -> None: ...
def session_poll_workunits(
    scheduler: PyScheduler, session: PySession, max_log_verbosity_level: int
) -> tuple[tuple[Workunit, ...], tuple[Workunit, ...]]: ...
def session_run_interactive_process(
    session: PySession, process: InteractiveProcess, process_config: ProcessExecutionEnvironment
) -> InteractiveProcessResult: ...
def session_get_metrics(session: PySession) -> dict[str, int]: ...
def session_get_observation_histograms(
    scheduler: PyScheduler, session: PySession
) -> dict[str, Any]: ...
def session_record_test_observation(
    scheduler: PyScheduler, session: PySession, value: int
) -> None: ...
def session_isolated_shallow_clone(session: PySession, build_id: str) -> PySession: ...
def session_wait_for_tail_tasks(
    scheduler: PyScheduler, session: PySession, timeout: float
) -> None: ...
def graph_len(scheduler: PyScheduler) -> int: ...
def graph_visualize(scheduler: PyScheduler, session: PySession, path: str) -> None: ...
def graph_invalidate_paths(scheduler: PyScheduler, paths: Iterable[str]) -> int: ...
def graph_invalidate_all_paths(scheduler: PyScheduler) -> int: ...
def graph_invalidate_all(scheduler: PyScheduler) -> None: ...
def check_invalidation_watcher_liveness(scheduler: PyScheduler) -> None: ...
def validate_reachability(scheduler: PyScheduler) -> None: ...
def rule_graph_consumed_types(
    scheduler: PyScheduler, param_types: Sequence[type], product_type: type
) -> list[type]: ...
def rule_graph_rule_gets(
    scheduler: PyScheduler,
) -> dict[Callable, list[tuple[type, list[type], Callable]]]: ...
def rule_graph_visualize(scheduler: PyScheduler, path: str) -> None: ...
def rule_subgraph_visualize(
    scheduler: PyScheduler, param_types: Sequence[type], product_type: type, path: str
) -> None: ...
def garbage_collect_store(scheduler: PyScheduler, target_size_bytes: int) -> None: ...
def lease_files_in_graph(scheduler: PyScheduler, session: PySession) -> None: ...
def strongly_connected_components(
    adjacency_lists: Sequence[Tuple[Any, Sequence[Any]]]
) -> Sequence[Sequence[Any]]: ...
def hash_prefix_zero_bits(item: str) -> int: ...

# ------------------------------------------------------------------------------
# Selectors
# ------------------------------------------------------------------------------

_Output = TypeVar("_Output")
_Input = TypeVar("_Input")

class PyGeneratorResponseCall:
    @overload
    def __init__(
        self,
        output_type: type,
        args: tuple[Any, ...],
        input_arg0: dict[Any, type],
    ) -> None: ...
    @overload
    def __init__(self, output_type: type, args: tuple[Any, ...], input_arg0: _Input) -> None: ...
    @overload
    def __init__(
        self,
        output_type: type,
        args: tuple[Any, ...],
        input_arg0: type[_Input],
        input_arg1: _Input,
    ) -> None: ...
    @overload
    def __init__(
        self,
        output_type: type,
        args: tuple[Any, ...],
        input_arg0: type[_Input] | _Input,
        input_arg1: _Input | None = None,
    ) -> None: ...

class PyGeneratorResponseGet(Generic[_Output]):
    output_type: type[_Output]
    input_types: Sequence[type]
    inputs: Sequence[Any]

    @overload
    def __init__(self, output_type: type[_Output]) -> None: ...
    @overload
    def __init__(
        self,
        output_type: type[_Output],
        input_arg0: dict[Any, type],
    ) -> None: ...
    @overload
    def __init__(self, output_type: type[_Output], input_arg0: _Input) -> None: ...
    @overload
    def __init__(
        self,
        output_type: type[_Output],
        input_arg0: type[_Input],
        input_arg1: _Input,
    ) -> None: ...
    @overload
    def __init__(
        self,
        output_type: type[_Output],
        input_arg0: type[_Input] | _Input,
        input_arg1: _Input | None = None,
    ) -> None: ...

# ------------------------------------------------------------------------------
# (uncategorized)
# ------------------------------------------------------------------------------

class PyExecutionRequest:
    def __init__(
        self, *, poll: bool, poll_delay_in_ms: int | None, timeout_in_ms: int | None
    ) -> None: ...

class PyExecutionStrategyOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyNailgunServer:
    def port(self) -> int: ...

class PyRemotingOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyLocalStoreOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyScheduler:
    pass

class PySession:
    def __init__(
        self,
        *,
        scheduler: PyScheduler,
        dynamic_ui: bool,
        ui_use_prodash: bool,
        max_workunit_level: int,
        build_id: str,
        session_values: SessionValues,
        cancellation_latch: PySessionCancellationLatch,
    ) -> None: ...
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
    @property
    def session_values(self) -> SessionValues: ...

class PySessionCancellationLatch:
    def __init__(self) -> None: ...

class PyTasks:
    def __init__(self) -> None: ...

class PyTypes:
    def __init__(self, **kwargs: Any) -> None: ...

class PyStdioDestination:
    pass

class PyThreadLocals:
    @classmethod
    def get_for_current_thread(cls) -> PyThreadLocals: ...
    def set_for_current_thread(self) -> None: ...

class PollTimeout(Exception):
    pass

# Prefer to import these exception types from `pants.base.exceptions`

class EngineError(Exception):
    """Base exception used for errors originating from the native engine."""

class IntrinsicError(EngineError):
    """Exceptions raised for failures within intrinsic methods implemented in Rust."""

class IncorrectProductError(EngineError):
    """Exceptions raised when a rule's return value doesn't match its declared type."""
