use crate::context::Context;
use crate::core::{throw, Value};
use crate::externs;
use crate::nodes::MultiPlatformExecuteProcess;
use crate::nodes::{lift_digest, DownloadedFile, NodeResult, Snapshot};
use crate::tasks::Intrinsic;
use crate::types::Types;

use futures::compat::Future01CompatExt;
use futures::future::{self, BoxFuture, FutureExt, TryFutureExt};
use indexmap::IndexMap;

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
        inputs: vec![types.input_files_content],
      },
      Box::new(input_files_content_to_digest),
    );
    intrinsics.insert(
      Intrinsic {
        product: types.snapshot,
        inputs: vec![types.path_globs],
      },
      Box::new(path_globs_to_snapshot),
    );
    intrinsics.insert(
      Intrinsic {
        product: types.snapshot,
        inputs: vec![types.url_to_fetch],
      },
      Box::new(url_to_fetch_to_snapshot),
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
        product: types.files_content,
        inputs: vec![types.directory_digest],
      },
      Box::new(directory_digest_to_files_content),
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
        product: types.snapshot,
        inputs: vec![types.snapshot_subset],
      },
      Box::new(snapshot_subset_to_snapshot),
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
  let core = context.core.clone();
  let store = context.core.store();
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

    let maybe_stdout = store
      .load_file_bytes_with(result.stdout_digest, |bytes: &[u8]| bytes.to_owned())
      .await
      .map_err(|s| throw(&s))?;

    let maybe_stderr = store
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
      &core.types.construct_process_result,
      &[
        externs::store_bytes(&stdout_bytes),
        externs::store_bytes(&stderr_bytes),
        externs::store_i64(result.exit_code.into()),
        Snapshot::store_directory(&core, &result.output_directory),
        externs::unsafe_call(
          &core.types.construct_platform,
          &[externs::store_utf8(&platform_name)],
        ),
      ],
    ))
  }
  .boxed()
}

fn directory_digest_to_files_content(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  async move {
    let digest = lift_digest(&args[0]).map_err(|s| throw(&s))?;
    let snapshot = context
      .core
      .store()
      .contents_for_directory(digest)
      .compat()
      .await
      .and_then(move |files_content| Snapshot::store_files_content(&context, &files_content))
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

  async move {
    let input_digest = lift_digest(&externs::project_ignoring_type(&args[0], "digest"))?;
    let prefix = externs::project_str(&args[0], "prefix");
    let digest =
      store::Snapshot::strip_prefix(core.store(), input_digest, PathBuf::from(prefix)).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&core, &digest));
    res
  }
  .map_err(|e: String| throw(&e))
  .boxed()
}

fn add_prefix_request_to_digest(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core;
  async move {
    let input_digest = lift_digest(&externs::project_ignoring_type(&args[0], "digest"))?;
    let prefix = externs::project_str(&args[0], "prefix");
    let digest =
      store::Snapshot::add_prefix(core.store(), input_digest, PathBuf::from(prefix)).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&core, &digest));
    res
  }
  .map_err(|e: String| throw(&e))
  .boxed()
}

fn digest_to_snapshot(context: Context, args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core.clone();
  let store = context.core.store();
  async move {
    let digest = lift_digest(&args[0])?;
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
  let digests: Result<Vec<hashing::Digest>, String> = externs::project_multi(&args[0], "digests")
    .into_iter()
    .map(|val| lift_digest(&val))
    .collect();
  async move {
    let digest = store::Snapshot::merge_directories(core.store(), digests?).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&core, &digest));
    res
  }
  .map_err(|err: String| throw(&err))
  .boxed()
}

fn url_to_fetch_to_snapshot(
  context: Context,
  mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core.clone();
  async move {
    let snapshot = context
      .get(DownloadedFile(externs::acquire_key_for(
        args.pop().unwrap(),
      )?))
      .await?;
    Ok(Snapshot::store_snapshot(&core, &snapshot).map_err(|err| throw(&err))?)
  }
  .boxed()
}

fn path_globs_to_snapshot(
  context: Context,
  mut args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let core = context.core.clone();
  async move {
    let snapshot = context
      .get(Snapshot(externs::acquire_key_for(args.pop().unwrap())?))
      .await?;
    Ok(Snapshot::store_snapshot(&core, &snapshot).map_err(|err| throw(&err))?)
  }
  .boxed()
}

fn input_files_content_to_digest(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let file_values = externs::project_multi(&args[0], "dependencies");
  let digests: Vec<_> = file_values
    .iter()
    .map(|file| {
      let filename = externs::project_str(&file, "path");
      let path: PathBuf = filename.into();
      let bytes = bytes::Bytes::from(externs::project_bytes(&file, "content"));
      let is_executable = externs::project_bool(&file, "is_executable");

      let store = context.core.store();
      async move {
        let digest = store.store_file_bytes(bytes, true).await?;
        let snapshot = store
          .snapshot_of_one_file(path, digest, is_executable)
          .await?;
        let res: Result<_, String> = Ok(snapshot.digest);
        res
      }
    })
    .collect();

  async move {
    let digests = future::try_join_all(digests).await?;
    let digest = store::Snapshot::merge_directories(context.core.store(), digests).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&context.core, &digest));
    res
  }
  .map_err(|err: String| throw(&err))
  .boxed()
}

fn snapshot_subset_to_snapshot(
  context: Context,
  args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
  let globs = externs::project_ignoring_type(&args[0], "globs");
  let store = context.core.store();

  async move {
    let path_globs = Snapshot::lift_path_globs(&globs)?;
    let original_digest = lift_digest(&externs::project_ignoring_type(&args[0], "digest"))?;

    let snapshot = store::Snapshot::get_snapshot_subset(store, original_digest, path_globs).await?;

    Ok(Snapshot::store_snapshot(&context.core, &snapshot)?)
  }
  .map_err(|err: String| throw(&err))
  .boxed()
}
