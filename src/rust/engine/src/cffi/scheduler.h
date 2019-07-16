#ifndef __PANTS_SCHEDULER_CBINDGEN_H__
#define __PANTS_SCHEDULER_CBINDGEN_H__
/*
 * Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

// Handle is declared as a typedef rather than a wrapper struct because it avoids needing to wrap
// the inner handle/`void*` in a tuple or datatype at the ffi boundary. For most types that
// overhead would not be worth worrying about, but Handle is used often enough that it gives a 6%
// speedup to avoid the wrapping.

typedef void* Handle;


/* Generated with cbindgen:0.8.6 */

#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

/**
 * Thread- or task-local context for where the Logger should send log statements.
 * We do this in a per-thread way because we find that Pants threads generally are either
 * daemon-specific or user-facing. We make sure that every time we spawn a thread on the Python
 * side, we set the thread-local information, and every time we submit a Future to a tokio Runtime
 * on the rust side, we set the task-local information.
 */
typedef enum {
  Pantsd,
  Stderr,
} Destination;

typedef struct ExecutionRequest ExecutionRequest;

/**
 * Represents the state of an execution of a Graph.
 */
typedef struct Scheduler Scheduler;

/**
 * A Session represents a related series of requests (generally: one run of the pants CLI) on an
 * underlying Scheduler, and is a useful scope for metrics.
 * Both Scheduler and Session are exposed to python and expected to be used by multiple threads, so
 * they use internal mutability in order to avoid exposing locks to callers.
 */
typedef struct Session Session;

/**
 * Registry of native (rust) Intrinsic tasks and user (python) Tasks.
 */
typedef struct Tasks Tasks;

typedef struct Vec_PyResult Vec_PyResult;

/**
 * NB: When a PyResult is handed from Python to Rust, the Rust side destroys the handle. But when
 * it is passed from Rust to Python, Python must destroy the handle.
 */
typedef struct {
  bool is_throw;
  Handle handle;
} PyResult;

/**
 * Points to an array containing a series of values allocated by Python.
 * TODO: An interesting optimization might be possible where we avoid actually
 * allocating the values array for values_len == 1, and instead store the Handle in
 * the `handle_` field.
 */
typedef struct {
  Handle *handles_ptr;
  uint64_t handles_len;
  Handle handle_;
} HandleBuffer;

typedef uint64_t Id;

typedef struct {
  Id _0;
} TypeId;

typedef void ExternContext;

typedef PyResult (*CallExtern)(const ExternContext*, const Handle*, const Handle*const *, uint64_t);

/**
 * The result of an `identify` call, including the __hash__ of a Handle and a TypeId representing
 * the object's type.
 */
typedef struct {
  int64_t hash;
  TypeId type_id;
} Ident;

typedef struct {
  TypeId *ids_ptr;
  uint64_t ids_len;
  Handle handle_;
} TypeIdBuffer;

typedef struct {
  Ident *idents_ptr;
  uint64_t idents_len;
  Handle handle_;
} IdentBuffer;

/**
 * The response from a call to extern_generator_send. Gets include Idents for their Handles
 * in order to avoid roundtripping to intern them, and to eagerly trigger errors for unhashable
 * types on the python side where possible.
 */
typedef enum {
  Get,
  GetMulti,
  Broke,
  Throw,
} PyGeneratorResponse_Tag;

typedef struct {
  TypeId _0;
  Handle _1;
  Ident _2;
} Get_Body;

typedef struct {
  TypeIdBuffer _0;
  HandleBuffer _1;
  IdentBuffer _2;
} GetMulti_Body;

typedef struct {
  Handle _0;
} Broke_Body;

typedef struct {
  Handle _0;
} Throw_Body;

typedef struct {
  PyGeneratorResponse_Tag tag;
  union {
    Get_Body get;
    GetMulti_Body get_multi;
    Broke_Body broke;
    Throw_Body throw;
  };
} PyGeneratorResponse;

typedef PyGeneratorResponse (*GeneratorSendExtern)(const ExternContext*, const Handle*, const Handle*);

typedef TypeId (*GetTypeForExtern)(const ExternContext*, const Handle*);

typedef Ident (*IdentifyExtern)(const ExternContext*, const Handle*);

typedef bool (*EqualsExtern)(const ExternContext*, const Handle*, const Handle*);

typedef Handle (*CloneValExtern)(const ExternContext*, const Handle*);

typedef const void *RawHandle;

/**
 * A Handle that is currently being dropped. This wrapper exists to mark the pointer Send.
 */
typedef struct {
  RawHandle _0;
} DroppingHandle;

typedef void (*DropHandlesExtern)(const ExternContext*, const DroppingHandle*, uint64_t);

typedef struct {
  uint8_t *bytes_ptr;
  uint64_t bytes_len;
  Handle handle_;
} Buffer;

typedef Buffer (*TypeToStrExtern)(const ExternContext*, TypeId);

typedef Buffer (*ValToStrExtern)(const ExternContext*, const Handle*);

typedef Handle (*StoreTupleExtern)(const ExternContext*, const Handle*const *, uint64_t);

typedef Handle (*StoreBytesExtern)(const ExternContext*, const uint8_t*, uint64_t);

typedef Handle (*StoreUtf8Extern)(const ExternContext*, const uint8_t*, uint64_t);

typedef Handle (*StoreI64Extern)(const ExternContext*, int64_t);

typedef Handle (*StoreF64Extern)(const ExternContext*, double);

typedef Handle (*StoreBoolExtern)(const ExternContext*, bool);

typedef Handle (*ProjectIgnoringTypeExtern)(const ExternContext*, const Handle*, const uint8_t *field_name_ptr, uint64_t field_name_len);

typedef HandleBuffer (*ProjectMultiExtern)(const ExternContext*, const Handle*, const uint8_t *field_name_ptr, uint64_t field_name_len);

typedef Handle (*CreateExceptionExtern)(const ExternContext*, const uint8_t *str_ptr, uint64_t str_len);

/**
 * Points to an array of (byte) Buffers.
 * TODO: Because this is only ever passed from Python to Rust, it could just use
 * `project_multi_strs`.
 */
typedef struct {
  Buffer *bufs_ptr;
  uint64_t bufs_len;
  Handle handle_;
} BufferBuffer;

/**
 * Wraps a type id for use as a key in HashMaps and sets.
 */
typedef struct {
  Id id;
  TypeId type_id;
} Key;

typedef struct {
  const PyResult *nodes_ptr;
  uint64_t nodes_len;
  Vec_PyResult nodes;
} RawNodes;

typedef struct {
  Key _0;
} Function;

void *PyInit_native_engine(void);

PyResult capture_snapshots(Scheduler *scheduler_ptr, Handle path_globs_and_root_tuple_wrapper);

PyResult decompress_tarball(const char *tar_path, const char *output_dir);

PyResult execution_add_root_select(Scheduler *scheduler_ptr,
                                   ExecutionRequest *execution_request_ptr,
                                   HandleBuffer param_vals,
                                   TypeId product);

const ExecutionRequest *execution_request_create(void);

void execution_request_destroy(ExecutionRequest *ptr);

void externs_set(const ExternContext *context,
                 uint8_t log_level,
                 Handle none,
                 CallExtern call,
                 GeneratorSendExtern generator_send,
                 GetTypeForExtern get_type_for,
                 IdentifyExtern identify,
                 EqualsExtern equals,
                 CloneValExtern clone_val,
                 DropHandlesExtern drop_handles,
                 TypeToStrExtern type_to_str,
                 ValToStrExtern val_to_str,
                 StoreTupleExtern store_tuple,
                 StoreTupleExtern store_set,
                 StoreTupleExtern store_dict,
                 StoreBytesExtern store_bytes,
                 StoreUtf8Extern store_utf8,
                 StoreI64Extern store_i64,
                 StoreF64Extern store_f64,
                 StoreBoolExtern store_bool,
                 ProjectIgnoringTypeExtern project_ignoring_type,
                 ProjectMultiExtern project_multi,
                 CreateExceptionExtern create_exception);

void flush_log(void);

void garbage_collect_store(Scheduler *scheduler_ptr);

uint64_t graph_invalidate(Scheduler *scheduler_ptr, BufferBuffer paths_buf);

uint64_t graph_invalidate_all_paths(Scheduler *scheduler_ptr);

uint64_t graph_len(Scheduler *scheduler_ptr);

void graph_trace(Scheduler *scheduler_ptr,
                 ExecutionRequest *execution_request_ptr,
                 const char *path_ptr);

PyResult graph_visualize(Scheduler *scheduler_ptr, Session *session_ptr, const char *path_ptr);

void init_logging(uint64_t level, bool show_rust_3rdparty_logs);

void initnative_engine(void);

Key key_for(Handle value);

void lease_files_in_graph(Scheduler *scheduler_ptr);

PyResult match_path_globs(Handle path_globs, BufferBuffer paths_buf);

PyResult materialize_directories(Scheduler *scheduler_ptr,
                                 Handle directories_paths_and_digests_value);

PyResult merge_directories(Scheduler *scheduler_ptr, Handle directories_value);

void nodes_destroy(RawNodes *raw_nodes_ptr);

void override_thread_logging_destination(Destination destination);

void rule_graph_visualize(Scheduler *scheduler_ptr,
                          TypeIdBuffer subject_types,
                          const char *path_ptr);

void rule_subgraph_visualize(Scheduler *scheduler_ptr,
                             TypeId subject_type,
                             TypeId product_type,
                             const char *path_ptr);

/**
 * Given a set of Tasks and type information, creates a Scheduler.
 * The given Tasks struct will be cloned, so no additional mutation of the reference will
 * affect the created Scheduler.
 */
const Scheduler *scheduler_create(Tasks *tasks_ptr,
                                  Function construct_directory_digest,
                                  Function construct_snapshot,
                                  Function construct_file_content,
                                  Function construct_files_content,
                                  Function construct_process_result,
                                  TypeId type_address,
                                  TypeId type_path_globs,
                                  TypeId type_directory_digest,
                                  TypeId type_snapshot,
                                  TypeId type_merge_directories_request,
                                  TypeId type_directory_with_prefix_to_strip,
                                  TypeId type_files_content,
                                  TypeId type_dir,
                                  TypeId type_file,
                                  TypeId type_link,
                                  TypeId type_process_request,
                                  TypeId type_process_result,
                                  TypeId type_generator,
                                  TypeId type_url_to_fetch,
                                  TypeId type_string,
                                  TypeId type_bytes,
                                  Buffer build_root_buf,
                                  Buffer work_dir_buf,
                                  Buffer local_store_dir_buf,
                                  BufferBuffer ignore_patterns_buf,
                                  TypeIdBuffer root_type_ids,
                                  BufferBuffer remote_store_servers_buf,
                                  Buffer remote_execution_server,
                                  Buffer remote_execution_process_cache_namespace,
                                  Buffer remote_instance_name,
                                  Buffer remote_root_ca_certs_path_buffer,
                                  Buffer remote_oauth_bearer_token_path_buffer,
                                  uint64_t remote_store_thread_count,
                                  uint64_t remote_store_chunk_bytes,
                                  uint64_t remote_store_chunk_upload_timeout_seconds,
                                  uint64_t remote_store_rpc_retries,
                                  BufferBuffer remote_execution_extra_platform_properties_buf,
                                  uint64_t process_execution_parallelism,
                                  bool process_execution_cleanup_local_dirs);

void scheduler_destroy(Scheduler *scheduler_ptr);

const RawNodes *scheduler_execute(Scheduler *scheduler_ptr,
                                  Session *session_ptr,
                                  ExecutionRequest *execution_request_ptr);

/**
 * Prepares to fork by shutting down any background threads used for execution, and then
 * calling the given callback function (which should execute the fork) while holding exclusive
 * access to all relevant locks.
 */
PyResult scheduler_fork_context(Scheduler *scheduler_ptr, Function func);

/**
 * Returns a Handle representing a dictionary where key is metric name string and value is
 * metric value int.
 */
Handle scheduler_metrics(Scheduler *scheduler_ptr, Session *session_ptr);

const Session *session_create(Scheduler *scheduler_ptr,
                              bool should_render_ui,
                              uint64_t ui_worker_count);

void session_destroy(Session *ptr);

void set_panic_handler(void);

PyResult setup_pantsd_logger(const char *log_file_ptr, uint64_t level);

void setup_stderr_logger(uint64_t level);

void tasks_add_get(Tasks *tasks_ptr, TypeId product, TypeId subject);

void tasks_add_select(Tasks *tasks_ptr, TypeId product);

const Tasks *tasks_create(void);

void tasks_destroy(Tasks *tasks_ptr);

void tasks_task_begin(Tasks *tasks_ptr, Function func, TypeId output_type, bool cacheable);

void tasks_task_end(Tasks *tasks_ptr);

Handle val_for(Key key);

PyResult validator_run(Scheduler *scheduler_ptr);

extern void wrapped_initnative_engine(void);

void write_log(const char *msg, uint64_t level, const char *target);

#endif // __PANTS_SCHEDULER_CBINDGEN_H__

