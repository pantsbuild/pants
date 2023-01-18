// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::env::current_dir;
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
use pyo3::types::PyString;
use pyo3::{PyAny, PyRef, Python, ToPyObject};
use tokio::process;

use fs::{DigestTrie, DirectoryDigest, RelativePath, TypedPath};
use hashing::{Digest, EMPTY_DIGEST};
use process_execution::docker::{ImagePullPolicy, ImagePullScope, DOCKER, IMAGE_PULL_CACHE};
use process_execution::local::{
  apply_chroot, create_sandbox, prepare_workdir, setup_run_sh_script, KeepSandboxes,
};
use process_execution::{ManagedChild, Platform, ProcessExecutionStrategy};
use rule_graph::DependencyKey;
use stdio::TryCloneAsFile;
use store::{SnapshotOps, SubsetParams};

use workunit_store::{in_workunit, Level};

type IntrinsicFn =
  Box<dyn Fn(Context, Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> + Send + Sync>;

pub struct Intrinsics {
  intrinsics: IndexMap<Intrinsic, IntrinsicFn>,
}

// NB: Keep in sync with `rules()` in `src/python/pants/engine/fs.py`.
impl Intrinsics {
  pub fn new(types: &Types) -> Intrinsics {
    let mut intrinsics: IndexMap<Intrinsic, IntrinsicFn> = IndexMap::new();
    intrinsics.insert(
      Intrinsic::new(types.directory_digest, types.create_digest),
      Box::new(create_digest_to_digest),
    );
    intrinsics.insert(
      Intrinsic::new(types.directory_digest, types.path_globs),
      Box::new(path_globs_to_digest),
    );
    intrinsics.insert(
      Intrinsic::new(types.paths, types.path_globs),
      Box::new(path_globs_to_paths),
    );
    intrinsics.insert(
      Intrinsic::new(types.directory_digest, types.native_download_file),
      Box::new(download_file_to_digest),
    );
    intrinsics.insert(
      Intrinsic::new(types.snapshot, types.directory_digest),
      Box::new(digest_to_snapshot),
    );
    intrinsics.insert(
      Intrinsic::new(types.digest_contents, types.directory_digest),
      Box::new(directory_digest_to_digest_contents),
    );
    intrinsics.insert(
      Intrinsic::new(types.digest_entries, types.directory_digest),
      Box::new(directory_digest_to_digest_entries),
    );
    intrinsics.insert(
      Intrinsic::new(types.directory_digest, types.merge_digests),
      Box::new(merge_digests_request_to_digest),
    );
    intrinsics.insert(
      Intrinsic::new(types.directory_digest, types.remove_prefix),
      Box::new(remove_prefix_request_to_digest),
    );
    intrinsics.insert(
      Intrinsic::new(types.directory_digest, types.add_prefix),
      Box::new(add_prefix_request_to_digest),
    );
    intrinsics.insert(
      Intrinsic {
        product: types.process_result,
        inputs: vec![
          DependencyKey::new(types.process),
          DependencyKey::new(types.process_config_from_environment),
        ],
      },
      Box::new(process_request_to_process_result),
    );
    intrinsics.insert(
      Intrinsic::new(types.directory_digest, types.digest_subset),
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
        inputs: vec![
          DependencyKey::new(types.interactive_process),
          DependencyKey::new(types.process_config_from_environment),
        ],
      },
      Box::new(interactive_process),
    );
    intrinsics.insert(
      Intrinsic {
        product: types.docker_resolve_image_result,
        inputs: vec![DependencyKey::new(types.docker_resolve_image_request)],
      },
      Box::new(docker_resolve_image),
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
    let process_config: externs::process::PyProcessConfigFromEnvironment =
      Python::with_gil(|py| {
        args
          .pop()
          .unwrap()
          .as_ref()
          .extract(py)
          .map_err(|e| format!("{}", e))
      })?;
    let process_request =
      ExecuteProcess::lift(&context.core.store(), args.pop().unwrap(), process_config)
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
    let key = Key::from_value(args.pop().unwrap()).map_err(Failure::from)?;
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
  SymlinkEntry(RelativePath, PathBuf),
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
          let bytes = bytes::Bytes::from(externs::getattr::<Vec<u8>>(obj, "content").unwrap());
          let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
          new_file_count += 1;
          CreateDigestItem::FileContent(path, bytes, is_executable)
        } else if obj.hasattr("file_digest").unwrap() {
          let py_file_digest: PyFileDigest = externs::getattr(obj, "file_digest").unwrap();
          let is_executable: bool = externs::getattr(obj, "is_executable").unwrap();
          CreateDigestItem::FileEntry(path, py_file_digest.0, is_executable)
        } else if obj.hasattr("target").unwrap() {
          let target: String = externs::getattr(obj, "target").unwrap();
          CreateDigestItem::SymlinkEntry(path, PathBuf::from(target))
        } else {
          CreateDigestItem::Dir(path)
        }
      })
      .collect()
  };

  let mut typed_paths: Vec<TypedPath> = Vec::with_capacity(items.len());
  let mut file_digests: HashMap<PathBuf, Digest> = HashMap::with_capacity(items.len());
  let mut bytes_to_store: Vec<(Option<Digest>, Bytes)> = Vec::with_capacity(new_file_count);

  for item in &items {
    match item {
      CreateDigestItem::FileContent(path, bytes, is_executable) => {
        let digest = Digest::of_bytes(bytes);
        bytes_to_store.push((Some(digest), bytes.clone()));
        typed_paths.push(TypedPath::File {
          path,
          is_executable: *is_executable,
        });
        file_digests.insert(path.to_path_buf(), digest);
      }
      CreateDigestItem::FileEntry(path, digest, is_executable) => {
        typed_paths.push(TypedPath::File {
          path,
          is_executable: *is_executable,
        });
        file_digests.insert(path.to_path_buf(), *digest);
      }
      CreateDigestItem::SymlinkEntry(path, target) => {
        typed_paths.push(TypedPath::Link { path, target });
        file_digests.insert(path.to_path_buf(), EMPTY_DIGEST);
      }
      CreateDigestItem::Dir(path) => {
        typed_paths.push(TypedPath::Dir(path));
        file_digests.insert(path.to_path_buf(), EMPTY_DIGEST);
      }
    }
  }

  let store = context.core.store();
  let trie = DigestTrie::from_unique_paths(typed_paths, &file_digests).unwrap();
  async move {
    // The digests returned here are already in the `file_digests` map.
    let _ = store.store_file_bytes_batch(bytes_to_store, true).await?;
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
  in_workunit!(
    "interactive_process",
    Level::Debug,
      |_workunit| async move {
      let types = &context.core.types;
      let interactive_process_result = types.interactive_process_result;

      let (py_interactive_process, py_process, process_config): (Value, Value, externs::process::PyProcessConfigFromEnvironment) = Python::with_gil(|py| {
        let py_interactive_process = (*args[0]).as_ref(py);
        let py_process: Value = externs::getattr(py_interactive_process, "process").unwrap();
        let process_config = (*args[1])
          .as_ref(py)
          .extract()
          .unwrap();
        (py_interactive_process.extract().unwrap(), py_process, process_config)
      });
      match process_config.execution_strategy {
        ProcessExecutionStrategy::Docker(_) | ProcessExecutionStrategy::RemoteExecution(_) => Err("InteractiveProcess should not set docker_image or remote_execution".to_owned()),
        _ => Ok(())
      }?;
      let mut process = ExecuteProcess::lift(&context.core.store(), py_process, process_config).await?.process;
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
        None,
        None,
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
      command.envs(&process.env);

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
          let mut subprocess = ManagedChild::spawn(command, context.core.graceful_shutdown_timeout)?;
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
      if keep_sandboxes == KeepSandboxes::Always
        || keep_sandboxes == KeepSandboxes::OnFailure && code != 0 {
        tempdir.keep("interactive process");
        let do_setup_run_sh_script = |workdir_path| -> Result<(), String> {
          setup_run_sh_script(tempdir.path(), &process.env, &process.working_directory, &process.argv, workdir_path)
        };
        if run_in_workspace {
          let cwd = current_dir()
          .map_err(|e| format!("Could not detect current working directory: {err}", err = e))?;
          do_setup_run_sh_script(cwd.as_path())?;
        } else {
          do_setup_run_sh_script(tempdir.path())?;
        }
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
    }
  ).boxed()
}

fn docker_resolve_image(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  async move {
    let types = &context.core.types;
    let docker_resolve_image_result = types.docker_resolve_image_result;

    let (image_name, platform) = Python::with_gil(|py| {
      let py_docker_request = (*args[0]).as_ref(py);
      let image_name: String = externs::getattr(py_docker_request, "image_name").unwrap();
      let platform: String = externs::getattr(py_docker_request, "platform").unwrap();
      (image_name, platform)
    });

    let platform = Platform::try_from(platform)?;

    let docker = DOCKER.get().await?;
    let image_pull_scope = ImagePullScope::new(context.session.build_id());

    // Ensure that the image has been pulled.
    IMAGE_PULL_CACHE
      .pull_image(
        docker,
        &image_name,
        &platform,
        image_pull_scope,
        ImagePullPolicy::OnlyIfLatestOrMissing,
      )
      .await
      .map_err(|err| format!("Failed to pull image `{}`: {}", image_name, err))?;

    let image_metadata = docker.inspect_image(&image_name).await.map_err(|err| {
      format!(
        "Failed to resolve image ID for image `{}`: {:?}",
        &image_name, err
      )
    })?;
    let image_id = image_metadata
      .id
      .ok_or_else(|| format!("Image does not exist: `{}`", &image_name))?;

    let result = {
      let gil = Python::acquire_gil();
      let py = gil.python();
      externs::unsafe_call(
        py,
        docker_resolve_image_result,
        &[Value::from(PyString::new(py, &image_id).to_object(py))],
      )
    };
    Ok(result)
  }
  .boxed()
}
