use std::path::{Path, PathBuf};
use std::process::Stdio;

use crate::context::Context;
use crate::externs;
use crate::nodes::{
  lift_directory_digest, task_side_effected, DownloadedFile, MultiPlatformExecuteProcess,
  NodeResult, Paths, SessionValues, Snapshot,
};
use crate::python::{throw, Key, Value};
use crate::tasks::Intrinsic;
use crate::types::Types;
use crate::Failure;

use cpython::Python;
use fs::RelativePath;
use futures::future::{self, BoxFuture, FutureExt, TryFutureExt};
use hashing::{Digest, EMPTY_DIGEST};
use indexmap::IndexMap;
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
        inputs: vec![types.multi_platform_process, types.platform],
      },
      Box::new(multi_platform_process_request_to_process_result),
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
    intrinsic: Intrinsic,
    context: Context,
    args: Vec<Value>,
  ) -> NodeResult<Value> {
    let function = self
      .intrinsics
      .get(&intrinsic)
      .unwrap_or_else(|| panic!("Unrecognized intrinsic: {:?}", intrinsic));
    function(context, args).await
  }
}

fn multi_platform_process_request_to_process_result(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  async move {
    let process_val = &args[0];
    // TODO: The platform will be used in a followup.
    let _platform_val = &args[1];

    let process_request = MultiPlatformExecuteProcess::lift(process_val).map_err(|str| {
      throw(&format!(
        "Error lifting MultiPlatformExecuteProcess: {}",
        str
      ))
    })?;
    let result = context.get(process_request).await?.0;

    let maybe_stdout = context
      .core
      .store()
      .load_file_bytes_with(result.stdout_digest, |bytes: &[u8]| bytes.to_owned())
      .await
      .map_err(|s| throw(&s))?;

    let maybe_stderr = context
      .core
      .store()
      .load_file_bytes_with(result.stderr_digest, |bytes: &[u8]| bytes.to_owned())
      .await
      .map_err(|s| throw(&s))?;

    let stdout_bytes = maybe_stdout.ok_or_else(|| {
      throw(&format!(
        "Bytes from stdout Digest {:?} not found in store",
        result.stdout_digest
      ))
    })?;

    let stderr_bytes = maybe_stderr.ok_or_else(|| {
      throw(&format!(
        "Bytes from stderr Digest {:?} not found in store",
        result.stderr_digest
      ))
    })?;

    let platform_name: String = result.platform.into();
    let gil = Python::acquire_gil();
    let py = gil.python();
    Ok(externs::unsafe_call(
      context.core.types.process_result,
      &[
        externs::store_bytes(py, &stdout_bytes),
        Snapshot::store_file_digest(&context.core.types, &result.stdout_digest),
        externs::store_bytes(py, &stderr_bytes),
        Snapshot::store_file_digest(&context.core.types, &result.stderr_digest),
        externs::store_i64(result.exit_code.into()),
        Snapshot::store_directory_digest(&result.output_directory).map_err(|s| throw(&s))?,
        externs::unsafe_call(
          context.core.types.platform,
          &[externs::store_utf8(&platform_name)],
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
    let digest = lift_directory_digest(&args[0]).map_err(|s| throw(&s))?;
    let snapshot = context
      .core
      .store()
      .contents_for_directory(digest)
      .await
      .and_then(move |digest_contents| {
        let gil = Python::acquire_gil();
        let py = gil.python();
        Snapshot::store_digest_contents(py, &context, &digest_contents)
      })
      .map_err(|s| throw(&s))?;
    Ok(snapshot)
  }
  .boxed()
}

fn directory_digest_to_digest_entries(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  async move {
    let digest = lift_directory_digest(&args[0]).map_err(|s| throw(&s))?;
    let snapshot = context
      .core
      .store()
      .entries_for_directory(digest)
      .await
      .and_then(move |digest_entries| Snapshot::store_digest_entries(&context, &digest_entries))
      .map_err(|s| throw(&s))?;
    Ok(snapshot)
  }
  .boxed()
}

fn remove_prefix_request_to_digest(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core;
  let store = core.store();

  async move {
    let input_digest = lift_directory_digest(&externs::getattr(&args[0], "digest").unwrap())
      .map_err(|e| throw(&e))?;
    let prefix = externs::getattr_as_string(&args[0], "prefix");
    let prefix = RelativePath::new(PathBuf::from(prefix))
      .map_err(|e| throw(&format!("The `prefix` must be relative: {:?}", e)))?;
    let digest = store
      .strip_prefix(input_digest, prefix)
      .await
      .map_err(|e| throw(&format!("{:?}", e)))?;
    Snapshot::store_directory_digest(&digest).map_err(|s| throw(&s))
  }
  .boxed()
}

fn add_prefix_request_to_digest(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core;
  let store = core.store();
  async move {
    let input_digest = lift_directory_digest(&externs::getattr(&args[0], "digest").unwrap())
      .map_err(|e| throw(&e))?;
    let prefix = externs::getattr_as_string(&args[0], "prefix");
    let prefix = RelativePath::new(PathBuf::from(prefix))
      .map_err(|e| throw(&format!("The `prefix` must be relative: {:?}", e)))?;
    let digest = store
      .add_prefix(input_digest, prefix)
      .await
      .map_err(|e| throw(&format!("{:?}", e)))?;
    Snapshot::store_directory_digest(&digest).map_err(|s| throw(&s))
  }
  .boxed()
}

fn digest_to_snapshot(context: Context, args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
  let store = context.core.store();
  async move {
    let digest = lift_directory_digest(&args[0])?;
    let snapshot = store::Snapshot::from_digest(store, digest).await?;
    Snapshot::store_snapshot(snapshot)
  }
  .map_err(|e: String| throw(&e))
  .boxed()
}

fn merge_digests_request_to_digest(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core;
  let store = core.store();
  let digests: Result<Vec<hashing::Digest>, String> =
    externs::getattr::<Vec<Value>>(&args[0], "digests")
      .unwrap()
      .into_iter()
      .map(|val: Value| lift_directory_digest(&val))
      .collect();
  async move {
    let digest = store
      .merge(digests.map_err(|e| throw(&e))?)
      .await
      .map_err(|e| throw(&format!("{:?}", e)))?;
    Snapshot::store_directory_digest(&digest).map_err(|s| throw(&s))
  }
  .boxed()
}

fn download_file_to_digest(
  context: Context,
  mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  async move {
    let key = Key::from_value(args.pop().unwrap()).map_err(Failure::from_py_err)?;
    let digest = context.get(DownloadedFile(key)).await?;
    Snapshot::store_directory_digest(&digest).map_err(|s| throw(&s))
  }
  .boxed()
}

fn path_globs_to_digest(
  context: Context,
  mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  async move {
    let val = args.pop().unwrap();
    let path_globs = Snapshot::lift_path_globs(&val)
      .map_err(|e| throw(&format!("Failed to parse PathGlobs: {}", e)))?;
    let digest = context.get(Snapshot::from_path_globs(path_globs)).await?;
    Snapshot::store_directory_digest(&digest).map_err(|s| throw(&s))
  }
  .boxed()
}

fn path_globs_to_paths(
  context: Context,
  mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core.clone();
  async move {
    let val = args.pop().unwrap();
    let path_globs = Snapshot::lift_path_globs(&val)
      .map_err(|e| throw(&format!("Failed to parse PathGlobs: {}", e)))?;
    let paths = context.get(Paths::from_path_globs(path_globs)).await?;
    Paths::store_paths(&core, &paths).map_err(|e: String| throw(&e))
  }
  .boxed()
}

fn create_digest_to_digest(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let file_items = externs::collect_iterable(&args[0]).unwrap();
  let digests: Vec<_> = file_items
    .into_iter()
    .map(|file_item| {
      let path = externs::getattr_as_string(&file_item, "path");
      let store = context.core.store();
      async move {
        let path = RelativePath::new(PathBuf::from(path))
          .map_err(|e| format!("The `path` must be relative: {:?}", e))?;

        if externs::hasattr(&file_item, "content") {
          let bytes =
            bytes::Bytes::from(externs::getattr::<Vec<u8>>(&file_item, "content").unwrap());
          let is_executable: bool = externs::getattr(&file_item, "is_executable").unwrap();

          let digest = store.store_file_bytes(bytes, true).await?;
          let snapshot = store
            .snapshot_of_one_file(path, digest, is_executable)
            .await?;
          let res: Result<_, String> = Ok(snapshot.digest);
          res
        } else if externs::hasattr(&file_item, "file_digest") {
          let digest_obj = externs::getattr(&file_item, "file_digest")?;
          let digest = Snapshot::lift_file_digest(&digest_obj)?;
          let is_executable: bool = externs::getattr(&file_item, "is_executable").unwrap();
          let snapshot = store
            .snapshot_of_one_file(path, digest, is_executable)
            .await?;
          let res: Result<_, String> = Ok(snapshot.digest);
          res
        } else {
          store
            .create_empty_dir(path)
            .await
            .map_err(|e| format!("{:?}", e))
        }
      }
    })
    .collect();

  let store = context.core.store();
  async move {
    let digests = future::try_join_all(digests).await.map_err(|e| throw(&e))?;
    let digest = store
      .merge(digests)
      .await
      .map_err(|e| throw(&format!("{:?}", e)))?;
    Snapshot::store_directory_digest(&digest).map_err(|s| throw(&s))
  }
  .boxed()
}

fn digest_subset_to_digest(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let globs = externs::getattr(&args[0], "globs").unwrap();
  let store = context.core.store();

  async move {
    let path_globs = Snapshot::lift_prepared_path_globs(&globs).map_err(|e| throw(&e))?;
    let original_digest = lift_directory_digest(&externs::getattr(&args[0], "digest").unwrap())
      .map_err(|e| throw(&e))?;
    let subset_params = SubsetParams { globs: path_globs };
    let digest = store
      .subset(original_digest, subset_params)
      .await
      .map_err(|e| throw(&format!("{:?}", e)))?;
    Snapshot::store_directory_digest(&digest).map_err(|s| throw(&s))
  }
  .boxed()
}

fn session_values(context: Context, _args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
  async move { context.get(SessionValues).await }.boxed()
}

fn interactive_process(
  context: Context,
  mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  async move {
    let types = &context.core.types;
    let interactive_process_result = types.interactive_process_result;

    let value: Value = args.pop().unwrap();

    let argv: Vec<String> = externs::getattr(&value, "argv").unwrap();
    if argv.is_empty() {
      return Err("Empty argv list not permitted".to_owned().into());
    }

    let run_in_workspace: bool = externs::getattr(&value, "run_in_workspace").unwrap();
    let restartable: bool = externs::getattr(&value, "restartable").unwrap();
    let input_digest_value: Value = externs::getattr(&value, "input_digest").unwrap();
    let input_digest: Digest = lift_directory_digest(&input_digest_value)?;
    let env = externs::getattr_from_frozendict(&value, "env");
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
        .materialize_directory(destination, input_digest)
        .await?;
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

    command.kill_on_drop(true);

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
        let mut subprocess = command
          .spawn()
          .map_err(|e| format!("Error executing interactive process: {}", e))?;
        tokio::select! {
          _ = session.cancelled() => {
            // The Session was cancelled: kill the process, and then wait for it to exit (to avoid
            // zombies).
            subprocess.kill().map_err(|e| format!("Failed to interrupt child process: {}", e)).await?;
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
    Ok(
      externs::unsafe_call(
        interactive_process_result,
        &[externs::store_i64(i64::from(code))],
      ),
    )
  }.boxed()
}
