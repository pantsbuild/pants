use crate::context::Context;
use crate::core::{throw, Value};
use crate::externs;
use crate::nodes::MultiPlatformExecuteProcess;
use crate::nodes::{
  lift_directory_digest, DownloadedFile, NodeResult, Paths, SessionValues, Snapshot,
};
use crate::tasks::Intrinsic;
use crate::types::Types;
use crate::Failure;

use fs::RelativePath;
use futures::compat::Future01CompatExt;
use futures::future::{self, BoxFuture, FutureExt, TryFutureExt};
use indexmap::IndexMap;
use store::{SnapshotOps, SubsetParams};

use std::path::PathBuf;

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

    let process_request = MultiPlatformExecuteProcess::lift(&context.core.types, process_val)
      .map_err(|str| {
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

    let stdout_bytes = maybe_stdout
      .map(|(bytes, _load_metadata)| bytes)
      .ok_or_else(|| {
        throw(&format!(
          "Bytes from stdout Digest {:?} not found in store",
          result.stdout_digest
        ))
      })?;

    let stderr_bytes = maybe_stderr
      .map(|(bytes, _load_metadata)| bytes)
      .ok_or_else(|| {
        throw(&format!(
          "Bytes from stderr Digest {:?} not found in store",
          result.stderr_digest
        ))
      })?;

    let platform_name: String = result.platform.into();
    Ok(externs::unsafe_call(
      context.core.types.process_result,
      &[
        externs::store_bytes(&stdout_bytes),
        externs::store_bytes(&stderr_bytes),
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
    let digest = lift_directory_digest(&context.core.types, &args[0]).map_err(|s| throw(&s))?;
    let snapshot = context
      .core
      .store()
      .contents_for_directory(digest)
      .compat()
      .await
      .and_then(move |digest_contents| Snapshot::store_digest_contents(&context, &digest_contents))
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
    let input_digest = lift_directory_digest(
      &core.types,
      &externs::project_ignoring_type(&args[0], "digest"),
    )
    .map_err(|e| throw(&e))?;
    let prefix = externs::project_str(&args[0], "prefix");
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
    let input_digest = lift_directory_digest(
      &core.types,
      &externs::project_ignoring_type(&args[0], "digest"),
    )
    .map_err(|e| throw(&e))?;
    let prefix = externs::project_str(&args[0], "prefix");
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
  let core = context.core.clone();
  let store = context.core.store();
  async move {
    let digest = lift_directory_digest(&context.core.types, &args[0])?;
    let snapshot = store::Snapshot::from_digest(store, digest).await?;
    Snapshot::store_snapshot(&core, &snapshot)
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
  let digests: Result<Vec<hashing::Digest>, String> = externs::project_multi(&args[0], "digests")
    .into_iter()
    .map(|val| lift_directory_digest(&core.types, &val))
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
    let key = externs::key_for(args.pop().unwrap()).map_err(Failure::from_py_err)?;
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
  let file_contents_and_directories = externs::project_iterable(&args[0]);
  let digests: Vec<_> = file_contents_and_directories
    .into_iter()
    .map(|file_content_or_directory| {
      let path = externs::project_str(&file_content_or_directory, "path");
      let store = context.core.store();
      async move {
        let path = RelativePath::new(PathBuf::from(path))
          .map_err(|e| format!("The `path` must be relative: {:?}", e))?;

        if externs::hasattr(file_content_or_directory.as_ref(), "content") {
          let bytes = bytes::Bytes::from(externs::project_bytes(
            &file_content_or_directory,
            "content",
          ));
          let is_executable = externs::project_bool(&file_content_or_directory, "is_executable");

          let digest = store.store_file_bytes(bytes, true).await?;
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
  let globs = externs::project_ignoring_type(&args[0], "globs");
  let store = context.core.store();

  async move {
    let path_globs = Snapshot::lift_prepared_path_globs(&globs).map_err(|e| throw(&e))?;
    let original_digest = lift_directory_digest(
      &context.core.types,
      &externs::project_ignoring_type(&args[0], "digest"),
    )
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
