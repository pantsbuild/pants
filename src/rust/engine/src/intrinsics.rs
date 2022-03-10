// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::process::Stdio;
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

use fs::{
  safe_create_dir_all_ioerror, DirectoryDigest, Permissions, PreparedPathGlobs, RelativePath,
};
use futures::future::{self, BoxFuture, FutureExt, TryFutureExt};
use hashing::{Digest, EMPTY_DIGEST};
use indexmap::IndexMap;
use process_execution::{CacheName, ManagedChild, NamedCaches};
use pyo3::{PyRef, Python};
use stdio::TryCloneAsFile;
use store::{SnapshotOps, SubsetParams};
use tempfile::TempDir;
use tokio::process;

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
      .map_err(|e| throw(format!("Error lifting Process: {}", e)))
      .await?;

    let result = context.get(process_request).await?.0;

    let maybe_stdout = context
      .core
      .store()
      .load_file_bytes_with(result.stdout_digest, |bytes: &[u8]| bytes.to_owned())
      .await
      .map_err(throw)?;

    let maybe_stderr = context
      .core
      .store()
      .load_file_bytes_with(result.stderr_digest, |bytes: &[u8]| bytes.to_owned())
      .await
      .map_err(throw)?;

    let stdout_bytes = maybe_stdout.ok_or_else(|| {
      throw(format!(
        "Bytes from stdout Digest {:?} not found in store",
        result.stdout_digest
      ))
    })?;

    let stderr_bytes = maybe_stderr.ok_or_else(|| {
      throw(format!(
        "Bytes from stderr Digest {:?} not found in store",
        result.stderr_digest
      ))
    })?;

    let platform_name: String = result.platform.into();
    let gil = Python::acquire_gil();
    let py = gil.python();
    Ok(externs::unsafe_call(
      py,
      context.core.types.process_result,
      &[
        externs::store_bytes(py, &stdout_bytes),
        Snapshot::store_file_digest(py, result.stdout_digest).map_err(throw)?,
        externs::store_bytes(py, &stderr_bytes),
        Snapshot::store_file_digest(py, result.stderr_digest).map_err(throw)?,
        externs::store_i64(py, result.exit_code.into()),
        Snapshot::store_directory_digest(
          py,
          DirectoryDigest::todo_from_digest(result.output_directory),
        )
        .map_err(throw)?,
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
    })
    .map_err(throw)?;

    let digest_contents = context
      .core
      .store()
      .contents_for_directory(digest)
      .await
      .map_err(throw)?;

    let gil = Python::acquire_gil();
    Snapshot::store_digest_contents(gil.python(), &context, &digest_contents).map_err(throw)
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
    })
    .map_err(throw)?;
    let snapshot = context
      .core
      .store()
      .entries_for_directory(digest)
      .await
      .and_then(move |digest_entries| {
        let gil = Python::acquire_gil();
        Snapshot::store_digest_entries(gil.python(), &context, &digest_entries)
      })
      .map_err(throw)?;
    Ok(snapshot)
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
        .map_err(|e| throw(format!("The `prefix` must be relative: {:?}", e)))?;
      let res: NodeResult<_> = Ok((py_remove_prefix.digest.clone(), prefix));
      res
    })?;
    let digest = context
      .core
      .store()
      .strip_prefix(digest, &prefix)
      .await
      .map_err(|e| throw(format!("{:?}", e)))?;
    let gil = Python::acquire_gil();
    Snapshot::store_directory_digest(gil.python(), digest).map_err(throw)
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
        .map_err(|e| throw(format!("The `prefix` must be relative: {:?}", e)))?;
      let res: NodeResult<(DirectoryDigest, RelativePath)> =
        Ok((py_add_prefix.digest.clone(), prefix));
      res
    })?;
    let digest = context
      .core
      .store()
      .add_prefix(digest, &prefix)
      .await
      .map_err(|e| throw(format!("{:?}", e)))?;
    let gil = Python::acquire_gil();
    Snapshot::store_directory_digest(gil.python(), digest).map_err(throw)
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
    Snapshot::store_snapshot(gil.python(), snapshot)
  }
  .map_err(throw)
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
    let digest = store
      .merge(digests)
      .await
      .map_err(|e| throw(format!("{:?}", e)))?;
    let gil = Python::acquire_gil();
    Snapshot::store_directory_digest(gil.python(), digest).map_err(throw)
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
    Snapshot::store_directory_digest(gil.python(), snapshot.into()).map_err(throw)
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
    Snapshot::store_directory_digest(gil.python(), snapshot.into()).map_err(throw)
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
    Paths::store_paths(gil.python(), &core, &paths).map_err(throw)
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
          let bytes = bytes::Bytes::from(externs::getattr::<Vec<u8>>(obj, "content").unwrap());
          let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
          CreateDigestItem::FileContent(path, bytes, is_executable)
        } else if obj.hasattr("file_digest").unwrap() {
          let py_file_digest: PyFileDigest = externs::getattr(obj, "file_digest").unwrap();
          let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
          CreateDigestItem::FileEntry(path, py_file_digest.0, is_executable)
        } else {
          CreateDigestItem::Dir(path)
        }
      })
      .collect()
  };

  // TODO: Rather than creating independent Digests and then merging them, this should use
  // `DigestTrie::from_path_stats`.
  //   see https://github.com/pantsbuild/pants/pull/14569#issuecomment-1057286943
  let digest_futures: Vec<_> = items
    .into_iter()
    .map(|item| {
      let store = context.core.store();
      async move {
        match item {
          CreateDigestItem::FileContent(path, bytes, is_executable) => {
            let digest = store.store_file_bytes(bytes, true).await?;
            let snapshot = store
              .snapshot_of_one_file(path, digest, is_executable)
              .await?;
            let res: Result<DirectoryDigest, String> = Ok(snapshot.into());
            res
          }
          CreateDigestItem::FileEntry(path, digest, is_executable) => {
            let snapshot = store
              .snapshot_of_one_file(path, digest, is_executable)
              .await?;
            let res: Result<_, String> = Ok(snapshot.into());
            res
          }
          CreateDigestItem::Dir(path) => store
            .create_empty_dir(&path)
            .await
            .map_err(|e| format!("{:?}", e)),
        }
      }
    })
    .collect();

  let store = context.core.store();
  async move {
    let digests = future::try_join_all(digest_futures).await.map_err(throw)?;
    let digest = store
      .merge(digests)
      .await
      .map_err(|e| throw(format!("{:?}", e)))?;
    let gil = Python::acquire_gil();
    Snapshot::store_directory_digest(gil.python(), digest).map_err(throw)
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
      let res: NodeResult<(PreparedPathGlobs, Digest)> = Ok((
        Snapshot::lift_prepared_path_globs(py_path_globs).map_err(throw)?,
        lift_directory_digest(py_digest)
          .map_err(throw)?
          .todo_as_digest(),
      ));
      res
    })?;
    let subset_params = SubsetParams { globs: path_globs };
    let digest = store
      .subset(original_digest, subset_params)
      .await
      .map_err(|e| throw(format!("{:?}", e)))?;
    let gil = Python::acquire_gil();
    Snapshot::store_directory_digest(gil.python(), DirectoryDigest::todo_from_digest(digest))
      .map_err(throw)
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

    let (argv, run_in_workspace, restartable, input_digest, env, append_only_caches) = Python::with_gil(|py| {
      let py_interactive_process = (*args[0]).as_ref(py);
      let argv: Vec<String> = externs::getattr(py_interactive_process, "argv").unwrap();
      if argv.is_empty() {
        return Err("Empty argv list not permitted".to_owned());
      }
      let run_in_workspace: bool = externs::getattr(py_interactive_process, "run_in_workspace").unwrap();
      let restartable: bool = externs::getattr(py_interactive_process, "restartable").unwrap();
      let py_input_digest = externs::getattr(py_interactive_process, "input_digest").unwrap();
      let input_digest: Digest = lift_directory_digest(py_input_digest)?.todo_as_digest();
      let env: BTreeMap<String, String> = externs::getattr_from_str_frozendict(py_interactive_process, "env");

      let append_only_caches = externs::getattr_from_str_frozendict::<&str>(py_interactive_process, "append_only_caches")
        .into_iter()
        .map(|(name, dest)| Ok((CacheName::new(name)?, RelativePath::new(dest)?)))
        .collect::<Result<BTreeMap<_, _>, String>>()?;
      if !append_only_caches.is_empty() && run_in_workspace {
        return Err("Local interactive process cannot use append-only caches when run in workspace.".to_owned());
      }

      Ok((argv, run_in_workspace, restartable, input_digest, env, append_only_caches))
    })?;

    let session = context.session;

    if !restartable {
        task_side_effected()?;
    }

    let maybe_tempdir = if run_in_workspace {
      None
    } else {
      Some(TempDir::new().map_err(|err| format!("Error creating tempdir: {}", err))?)
    };

    if input_digest != EMPTY_DIGEST {
      if run_in_workspace {
        return Err(
          "Local interactive process should not attempt to materialize files when run in workspace.".to_owned().into()
        );
      }

      let destination = match maybe_tempdir {
        Some(ref dir) => dir.path().to_path_buf(),
        None => unreachable!(),
      };

      context
        .core
        .store()
        .materialize_directory(destination, input_digest, Permissions::Writable)
        .await?;
    }

    // TODO: `immutable_input_digests` are not supported for InteractiveProcess, but they would be
    // materialized here.
    //   see https://github.com/pantsbuild/pants/issues/13852
    if !append_only_caches.is_empty() {
       let named_caches = NamedCaches::new(context.core.named_caches_dir.clone());
       let named_cache_symlinks = named_caches
           .local_paths(&append_only_caches)
           .collect::<Vec<_>>();

       let workdir = match maybe_tempdir {
         Some(ref dir) => dir.path().to_path_buf(),
         None => unreachable!(),
       };

       for named_cache_symlink in named_cache_symlinks {
         safe_create_dir_all_ioerror(&named_cache_symlink.dst).map_err(|err| {
           format!(
             "Error making {} for local execution: {:?}",
             named_cache_symlink.dst.display(),
             err
           )
         })?;

         let src = workdir.join(&named_cache_symlink.src);
         if let Some(dir) = src.parent() {
           safe_create_dir_all_ioerror(dir).map_err(|err| {
             format!(
               "Error making {} for local execution: {:?}", dir.display(), err
             )
           })?;
         }
         symlink(&named_cache_symlink.dst, &src).map_err(|err| {
           format!(
             "Error linking {} -> {} for local execution: {:?}",
             src.display(),
             named_cache_symlink.dst.display(),
             err
           )
         })?;
       }
     }

    let p = Path::new(&argv[0]);
    let program_name = match maybe_tempdir {
      Some(ref tempdir) if p.is_relative() => {
        let mut buf = PathBuf::new();
        buf.push(tempdir);
        buf.push(p);
        buf
      }
      _ => p.to_path_buf(),
    };

    let mut command = process::Command::new(program_name);
    for arg in argv[1..].iter() {
      command.arg(arg);
    }

    if let Some(ref tempdir) = maybe_tempdir {
      command.current_dir(tempdir.path());
    }

    command.env_clear();
    command.envs(env);

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
              .map_err(|e| format!("Couldn't clone stdin: {}", e))?,
          ))
          .stdout(Stdio::from(
            term_stdout
              .try_clone_as_file()
              .map_err(|e| format!("Couldn't clone stdout: {}", e))?,
          ))
          .stderr(Stdio::from(
            term_stderr
              .try_clone_as_file()
              .map_err(|e| format!("Couldn't clone stderr: {}", e))?,
          ));
        let mut subprocess = ManagedChild::spawn(command)?;
        tokio::select! {
          _ = session.cancelled() => {
            // The Session was cancelled: attempt to kill the process group / process, and
            // then wait for it to exit (to avoid zombies).
            if let Err(e) = subprocess.graceful_shutdown_sync() {
              // Failed to kill the PGID: try the non-group form.
              log::warn!("Failed to kill spawned process group ({}). Will try killing only the top process.\n\
                         This is unexpected: please file an issue about this problem at \
                         [https://github.com/pantsbuild/pants/issues/new]", e);
              subprocess.kill().map_err(|e| format!("Failed to interrupt child process: {}", e)).await?;
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
