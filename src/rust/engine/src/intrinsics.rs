// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::str::FromStr;
use std::time::Duration;

use crate::context::Context;
use crate::externs;
use crate::externs::fs::{PyAddPrefix, PyFileDigest, PyMergeDigests, PyRemovePrefix};
use crate::nodes::{
    lift_directory_digest, task_side_effected, DownloadedFile, ExecuteProcess, NodeResult, Paths,
    RunId, SessionValues, Snapshot,
};
use crate::python::{throw, Key, Value};
use crate::tasks::Intrinsic;
use crate::types::Types;
use crate::Failure;

use bytes::Bytes;
use futures::future::{BoxFuture, FutureExt, TryFutureExt};
use futures::try_join;
use indexmap::IndexMap;
use pyo3::{PyAny, PyRef, Python, ToPyObject};
use tokio::process;

use fs::{DigestTrie, DirectoryDigest, PathStat, RelativePath};
use hashing::{Digest, EMPTY_DIGEST};
use process_execution::local::{apply_chroot, create_sandbox, prepare_workdir, KeepSandboxes};
use process_execution::ManagedChild;
use stdio::TryCloneAsFile;
use store::{SnapshotOps, SubsetParams};

type IntrinsicFn =
    Box<dyn Fn(Context, Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> + Send + Sync>;

pub struct Intrinsics {
    intrinsics: IndexMap<Intrinsic, IntrinsicFn>,
}

impl Intrinsics {
    pub fn new(types: &Types) -> Intrinsics {
        let mut intrinsics: IndexMap<Intrinsic, IntrinsicFn> = IndexMap::new();
        intrinsics.insert(
            Intrinsic {
                product: types.directory_digest,
                inputs: vec![types.create_digest],
            },
            Box::new(create_digest_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.directory_digest,
                inputs: vec![types.path_globs],
            },
            Box::new(path_globs_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.paths,
                inputs: vec![types.path_globs],
            },
            Box::new(path_globs_to_paths),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.directory_digest,
                inputs: vec![types.download_file],
            },
            Box::new(download_file_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.snapshot,
                inputs: vec![types.directory_digest],
            },
            Box::new(digest_to_snapshot),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.digest_contents,
                inputs: vec![types.directory_digest],
            },
            Box::new(directory_digest_to_digest_contents),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.digest_entries,
                inputs: vec![types.directory_digest],
            },
            Box::new(directory_digest_to_digest_entries),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.directory_digest,
                inputs: vec![types.merge_digests],
            },
            Box::new(merge_digests_request_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.directory_digest,
                inputs: vec![types.remove_prefix],
            },
            Box::new(remove_prefix_request_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.directory_digest,
                inputs: vec![types.add_prefix],
            },
            Box::new(add_prefix_request_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.process_result,
                inputs: vec![types.process],
            },
            Box::new(process_request_to_process_result),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.directory_digest,
                inputs: vec![types.digest_subset],
            },
            Box::new(digest_subset_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.session_values,
                inputs: vec![],
            },
            Box::new(session_values),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.run_id,
                inputs: vec![],
            },
            Box::new(run_id),
        );
        intrinsics.insert(
            Intrinsic {
                product: types.interactive_process_result,
                inputs: vec![types.interactive_process],
            },
            Box::new(interactive_process),
        );
        Intrinsics { intrinsics }
    }

    pub fn keys(&self) -> impl Iterator<Item = &Intrinsic> {
        self.intrinsics.keys()
    }

    pub async fn run(
        &self,
        intrinsic: &Intrinsic,
        context: Context,
        args: Vec<Value>,
    ) -> NodeResult<Value> {
        let function = self
            .intrinsics
            .get(intrinsic)
            .unwrap_or_else(|| panic!("Unrecognized intrinsic: {:?}", intrinsic));
        function(context, args).await
    }
}

fn process_request_to_process_result(
    context: Context,
    mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let process_request = ExecuteProcess::lift(&context.core.store(), args.pop().unwrap())
            .map_err(|e| e.enrich("Error lifting Process"))
            .await?;

        let result = context.get(process_request).await?.result;

        let store = context.core.store();
        let (stdout_bytes, stderr_bytes) = try_join!(
            store
                .load_file_bytes_with(result.stdout_digest, |bytes: &[u8]| bytes.to_owned())
                .map_err(|e| e.enrich("Bytes from stdout")),
            store
                .load_file_bytes_with(result.stderr_digest, |bytes: &[u8]| bytes.to_owned())
                .map_err(|e| e.enrich("Bytes from stderr"))
        )?;

        let platform_name: String = result.platform.into();
        let gil = Python::acquire_gil();
        let py = gil.python();
        Ok(externs::unsafe_call(
            py,
            context.core.types.process_result,
            &[
                externs::store_bytes(py, &stdout_bytes),
                Snapshot::store_file_digest(py, result.stdout_digest)?,
                externs::store_bytes(py, &stderr_bytes),
                Snapshot::store_file_digest(py, result.stderr_digest)?,
                externs::store_i64(py, result.exit_code.into()),
                Snapshot::store_directory_digest(py, result.output_directory)?,
                externs::unsafe_call(
                    py,
                    context.core.types.platform,
                    &[externs::store_utf8(py, &platform_name)],
                ),
                externs::unsafe_call(
                    py,
                    context.core.types.process_result_metadata,
                    &[
                        result
                            .metadata
                            .total_elapsed
                            .map(|d| externs::store_u64(py, Duration::from(d).as_millis() as u64))
                            .unwrap_or_else(|| Value::from(py.None())),
                        externs::store_utf8(py, result.metadata.source.into()),
                        externs::store_u64(py, result.metadata.source_run_id.0.into()),
                    ],
                ),
            ],
        ))
    }
    .boxed()
}

fn directory_digest_to_digest_contents(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let digest = Python::with_gil(|py| {
            let py_digest = (*args[0]).as_ref(py);
            lift_directory_digest(py_digest)
        })?;

        let digest_contents = context.core.store().contents_for_directory(digest).await?;

        let gil = Python::acquire_gil();
        let value = Snapshot::store_digest_contents(gil.python(), &context, &digest_contents)?;
        Ok(value)
    }
    .boxed()
}

fn directory_digest_to_digest_entries(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let digest = Python::with_gil(|py| {
            let py_digest = (*args[0]).as_ref(py);
            lift_directory_digest(py_digest)
        })?;
        let digest_entries = context.core.store().entries_for_directory(digest).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_digest_entries(gil.python(), &context, &digest_entries)?;
        Ok(value)
    }
    .boxed()
}

fn remove_prefix_request_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let (digest, prefix) = Python::with_gil(|py| {
            let py_remove_prefix = (*args[0])
                .as_ref(py)
                .extract::<PyRef<PyRemovePrefix>>()
                .map_err(|e| throw(format!("{}", e)))?;
            let prefix = RelativePath::new(&py_remove_prefix.prefix)
                .map_err(|e| throw(format!("The `prefix` must be relative: {}", e)))?;
            let res: NodeResult<_> = Ok((py_remove_prefix.digest.clone(), prefix));
            res
        })?;
        let digest = context.core.store().strip_prefix(digest, &prefix).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_directory_digest(gil.python(), digest)?;
        Ok(value)
    }
    .boxed()
}

fn add_prefix_request_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let (digest, prefix) = Python::with_gil(|py| {
            let py_add_prefix = (*args[0])
                .as_ref(py)
                .extract::<PyRef<PyAddPrefix>>()
                .map_err(|e| throw(format!("{}", e)))?;
            let prefix = RelativePath::new(&py_add_prefix.prefix)
                .map_err(|e| throw(format!("The `prefix` must be relative: {}", e)))?;
            let res: NodeResult<(DirectoryDigest, RelativePath)> =
                Ok((py_add_prefix.digest.clone(), prefix));
            res
        })?;
        let digest = context.core.store().add_prefix(digest, &prefix).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_directory_digest(gil.python(), digest)?;
        Ok(value)
    }
    .boxed()
}

fn digest_to_snapshot(context: Context, args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
    let store = context.core.store();
    async move {
        let digest = Python::with_gil(|py| {
            let py_digest = (*args[0]).as_ref(py);
            lift_directory_digest(py_digest)
        })?;
        let snapshot = store::Snapshot::from_digest(store, digest).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_snapshot(gil.python(), snapshot)?;
        Ok(value)
    }
    .boxed()
}

fn merge_digests_request_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let core = context.core;
    let store = core.store();
    async move {
        let digests = Python::with_gil(|py| {
            (*args[0])
                .as_ref(py)
                .extract::<PyRef<PyMergeDigests>>()
                .map(|py_merge_digests| py_merge_digests.0.clone())
                .map_err(|e| throw(format!("{}", e)))
        })?;
        let digest = store.merge(digests).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_directory_digest(gil.python(), digest)?;
        Ok(value)
    }
    .boxed()
}

fn download_file_to_digest(
    context: Context,
    mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let key = Key::from_value(args.pop().unwrap()).map_err(Failure::from_py_err)?;
        let snapshot = context.get(DownloadedFile(key)).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_directory_digest(gil.python(), snapshot.into())?;
        Ok(value)
    }
    .boxed()
}

fn path_globs_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let path_globs = Python::with_gil(|py| {
            let py_path_globs = (*args[0]).as_ref(py);
            Snapshot::lift_path_globs(py_path_globs)
        })
        .map_err(|e| throw(format!("Failed to parse PathGlobs: {}", e)))?;
        let snapshot = context.get(Snapshot::from_path_globs(path_globs)).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_directory_digest(gil.python(), snapshot.into())?;
        Ok(value)
    }
    .boxed()
}

fn path_globs_to_paths(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let core = context.core.clone();
    async move {
        let path_globs = Python::with_gil(|py| {
            let py_path_globs = (*args[0]).as_ref(py);
            Snapshot::lift_path_globs(py_path_globs)
        })
        .map_err(|e| throw(format!("Failed to parse PathGlobs: {}", e)))?;
        let paths = context.get(Paths::from_path_globs(path_globs)).await?;
        let gil = Python::acquire_gil();
        let value = Paths::store_paths(gil.python(), &core, &paths)?;
        Ok(value)
    }
    .boxed()
}

enum CreateDigestItem {
    FileContent(RelativePath, bytes::Bytes, bool),
    FileEntry(RelativePath, Digest, bool),
    Dir(RelativePath),
}

fn create_digest_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let mut new_file_count = 0;

    let items: Vec<CreateDigestItem> = {
        let gil = Python::acquire_gil();
        let py = gil.python();
        let py_create_digest = (*args[0]).as_ref(py);
        externs::collect_iterable(py_create_digest)
            .unwrap()
            .into_iter()
            .map(|obj| {
                let raw_path: String = externs::getattr(obj, "path").unwrap();
                let path = RelativePath::new(PathBuf::from(raw_path)).unwrap();
                if obj.hasattr("content").unwrap() {
                    let bytes =
                        bytes::Bytes::from(externs::getattr::<Vec<u8>>(obj, "content").unwrap());
                    let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
                    new_file_count += 1;
                    CreateDigestItem::FileContent(path, bytes, is_executable)
                } else if obj.hasattr("file_digest").unwrap() {
                    let py_file_digest: PyFileDigest =
                        externs::getattr(obj, "file_digest").unwrap();
                    let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
                    CreateDigestItem::FileEntry(path, py_file_digest.0, is_executable)
                } else {
                    CreateDigestItem::Dir(path)
                }
            })
            .collect()
    };

    let mut path_stats: Vec<PathStat> = Vec::with_capacity(items.len());
    let mut file_digests: HashMap<PathBuf, Digest> = HashMap::with_capacity(items.len());
    let mut bytes_to_store: Vec<(Option<Digest>, Bytes)> = Vec::with_capacity(new_file_count);

    for item in items {
        match item {
            CreateDigestItem::FileContent(path, bytes, is_executable) => {
                let digest = Digest::of_bytes(&bytes);
                bytes_to_store.push((Some(digest), bytes));
                let stat = fs::File {
                    path: path.to_path_buf(),
                    is_executable,
                };
                path_stats.push(PathStat::file(path.to_path_buf(), stat));
                file_digests.insert(path.to_path_buf(), digest);
            }
            CreateDigestItem::FileEntry(path, digest, is_executable) => {
                let stat = fs::File {
                    path: path.to_path_buf(),
                    is_executable,
                };
                path_stats.push(PathStat::file(path.to_path_buf(), stat));
                file_digests.insert(path.to_path_buf(), digest);
            }
            CreateDigestItem::Dir(path) => {
                let stat = fs::Dir(path.to_path_buf());
                path_stats.push(PathStat::dir(path.to_path_buf(), stat));
                file_digests.insert(path.to_path_buf(), EMPTY_DIGEST);
            }
        }
    }

    let store = context.core.store();
    async move {
        // The digests returned here are already in the `file_digests` map.
        let _ = store.store_file_bytes_batch(bytes_to_store, true).await?;
        let trie = DigestTrie::from_path_stats(path_stats, &file_digests)?;

        let gil = Python::acquire_gil();
        let value = Snapshot::store_directory_digest(gil.python(), trie.into())?;
        Ok(value)
    }
    .boxed()
}

fn digest_subset_to_digest(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    let store = context.core.store();
    async move {
        let (path_globs, original_digest) = Python::with_gil(|py| {
            let py_digest_subset = (*args[0]).as_ref(py);
            let py_path_globs = externs::getattr(py_digest_subset, "globs").unwrap();
            let py_digest = externs::getattr(py_digest_subset, "digest").unwrap();
            let res: NodeResult<_> = Ok((
                Snapshot::lift_prepared_path_globs(py_path_globs)?,
                lift_directory_digest(py_digest)?,
            ));
            res
        })?;
        let subset_params = SubsetParams { globs: path_globs };
        let digest = store.subset(original_digest, subset_params).await?;
        let gil = Python::acquire_gil();
        let value = Snapshot::store_directory_digest(gil.python(), digest)?;
        Ok(value)
    }
    .boxed()
}

fn session_values(context: Context, _args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
    async move { context.get(SessionValues).await }.boxed()
}

fn run_id(context: Context, _args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
    async move { context.get(RunId).await }.boxed()
}

fn interactive_process(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
    let types = &context.core.types;
    let interactive_process_result = types.interactive_process_result;

    let (py_interactive_process, py_process): (Value, Value) = Python::with_gil(|py| {
      let py_interactive_process = (*args[0]).as_ref(py);
      let py_process: Value = externs::getattr(py_interactive_process, "process").unwrap();
      (py_interactive_process.extract().unwrap(), py_process)
    });
    let mut process = ExecuteProcess::lift_process(&context.core.store(), py_process).await?;
    let (run_in_workspace, restartable, keep_sandboxes) = Python::with_gil(|py| {
      let py_interactive_process_obj = py_interactive_process.to_object(py);
      let py_interactive_process = py_interactive_process_obj.as_ref(py);
      let run_in_workspace: bool = externs::getattr(py_interactive_process, "run_in_workspace").unwrap();
      let restartable: bool = externs::getattr(py_interactive_process, "restartable").unwrap();
      let keep_sandboxes_value: &PyAny = externs::getattr(py_interactive_process, "keep_sandboxes").unwrap();
      let keep_sandboxes = KeepSandboxes::from_str(externs::getattr(keep_sandboxes_value, "value").unwrap()).unwrap();
      (run_in_workspace, restartable, keep_sandboxes)
    });

    let session = context.session;

    let mut tempdir = create_sandbox(
      context.core.executor.clone(),
      &context.core.local_execution_root_dir,
      "interactive process",
      keep_sandboxes,
    )?;
    prepare_workdir(
      tempdir.path().to_owned(),
      &process,
      process.input_digests.input_files.clone(),
      context.core.store(),
      context.core.executor.clone(),
      &context.core.named_caches,
      &context.core.immutable_inputs,
    )
    .await?;
    apply_chroot(tempdir.path().to_str().unwrap(), &mut process);

    let p = Path::new(&process.argv[0]);
    // TODO: Deprecate this program name calculation, and recommend `{chroot}` replacement in args
    // instead.
    let program_name = if !run_in_workspace && p.is_relative() {
      let mut buf = PathBuf::new();
      buf.push(tempdir.path());
      buf.push(p);
      buf
    } else {
      p.to_path_buf()
    };

    let mut command = process::Command::new(program_name);
    if !run_in_workspace {
      command.current_dir(tempdir.path());
    }
    for arg in process.argv[1..].iter() {
      command.arg(arg);
    }

    command.env_clear();
    command.envs(process.env);

    if !restartable {
        task_side_effected()?;
    }

      let exit_status = session.clone()
        .with_console_ui_disabled(async move {
          // Once any UI is torn down, grab exclusive access to the console.
          let (term_stdin, term_stdout, term_stderr) =
            stdio::get_destination().exclusive_start(Box::new(|_| {
              // A stdio handler that will immediately trigger logging.
              Err(())
            }))?;
          // NB: Command's stdio methods take ownership of a file-like to use, so we use
          // `TryCloneAsFile` here to `dup` our thread-local stdio.
          command
            .stdin(Stdio::from(
              term_stdin
                .try_clone_as_file()
                .map_err(|e| format!("Couldn't clone stdin: {e}"))?,
            ))
            .stdout(Stdio::from(
              term_stdout
                .try_clone_as_file()
                .map_err(|e| format!("Couldn't clone stdout: {e}"))?,
            ))
            .stderr(Stdio::from(
              term_stderr
                .try_clone_as_file()
                .map_err(|e| format!("Couldn't clone stderr: {e}"))?,
            ));
          let mut subprocess =
              ManagedChild::spawn(&mut command, Some(context.core.graceful_shutdown_timeout))
                .map_err(|e| format!("Error executing interactive process: {e}"))?;
          tokio::select! {
            _ = session.cancelled() => {
              // The Session was cancelled: attempt to kill the process group / process, and
              // then wait for it to exit (to avoid zombies).
              if let Err(e) = subprocess.attempt_shutdown_sync() {
                // Failed to kill the PGID: try the non-group form.
                log::warn!("Failed to kill spawned process group ({}). Will try killing only the top process.\n\
                          This is unexpected: please file an issue about this problem at \
                          [https://github.com/pantsbuild/pants/issues/new]", e);
                subprocess.kill().map_err(|e| format!("Failed to interrupt child process: {e}")).await?;
              };
              subprocess.wait().await.map_err(|e| e.to_string())
            }
            exit_status = subprocess.wait() => {
              // The process exited.
              exit_status.map_err(|e| e.to_string())
            }
          }
        })
        .await?;

    let code = exit_status.code().unwrap_or(-1);
    if keep_sandboxes == KeepSandboxes::OnFailure && code != 0 {
      tempdir.keep("interactive process");
    }

    let result = {
      let gil = Python::acquire_gil();
      let py = gil.python();
      externs::unsafe_call(
        py,
        interactive_process_result,
        &[externs::store_i64(py, i64::from(code))],
      )
    };
    Ok(result)
  }.boxed()
}
