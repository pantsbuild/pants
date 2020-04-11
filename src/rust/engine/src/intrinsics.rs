use crate::context::Context;
use crate::core::{throw, TypeId, Value};
use crate::externs;
use crate::nodes::MultiPlatformExecuteProcess;
use crate::nodes::{lift_digest, DownloadedFile, NodeFuture, Snapshot};
use boxfuture::Boxable;
use bytes;
use futures::future::{self as future03, TryFutureExt};
use futures01::{future, Future};
use hashing;
use std::path::PathBuf;

pub fn run_intrinsic(
  input: TypeId,
  product: TypeId,
  context: Context,
  value: Value,
) -> NodeFuture<Value> {
  let types = &context.core.types;
  if product == types.process_result && input == types.multi_platform_process_request {
    multi_platform_process_request_to_process_result(context, value)
  } else if product == types.files_content && input == types.directory_digest {
    directory_digest_to_files_content(context, value)
  } else if product == types.directory_digest && input == types.directory_with_prefix_to_strip {
    directory_with_prefix_to_strip_to_digest(context, value)
  } else if product == types.directory_digest && input == types.directory_with_prefix_to_add {
    directory_with_prefix_to_add_to_digest(context, value)
  } else if product == types.snapshot && input == types.directory_digest {
    digest_to_snapshot(context, value)
  } else if product == types.directory_digest && input == types.directories_to_merge {
    directories_to_merge_to_digest(context, value)
  } else if product == types.snapshot && input == types.url_to_fetch {
    url_to_fetch_to_snapshot(context, value)
  } else if product == types.snapshot && input == types.path_globs {
    path_globs_to_snapshot(context, value)
  } else if product == types.directory_digest && input == types.input_files_content {
    input_files_content_to_digest(context, value)
  } else if product == types.snapshot && input == types.snapshot_subset {
    snapshot_subset_to_snapshot(context, value)
  } else {
    panic!("Unrecognized intrinsic: {:?} -> {:?}", input, product)
  }
}

fn multi_platform_process_request_to_process_result(
  context: Context,
  value: Value,
) -> NodeFuture<Value> {
  let core = context.core.clone();
  future::result(MultiPlatformExecuteProcess::lift(&value).map_err(|str| {
    throw(&format!(
      "Error lifting MultiPlatformExecuteProcess: {}",
      str
    ))
  }))
  .and_then(move |process_request| context.get(process_request))
  .map(move |result| {
    let platform_name: String = result.0.platform.into();
    externs::unsafe_call(
      &core.types.construct_process_result,
      &[
        externs::store_bytes(&result.0.stdout),
        externs::store_bytes(&result.0.stderr),
        externs::store_i64(result.0.exit_code.into()),
        Snapshot::store_directory(&core, &result.0.output_directory),
        externs::unsafe_call(
          &core.types.construct_platform,
          &[externs::store_utf8(&platform_name)],
        ),
      ],
    )
  })
  .to_boxed()
}

fn directory_digest_to_files_content(
  context: Context,
  directory_digest_val: Value,
) -> NodeFuture<Value> {
  future::result(lift_digest(&directory_digest_val).map_err(|str| throw(&str)))
    .and_then(move |digest| {
      context
        .core
        .store()
        .contents_for_directory(digest)
        .map_err(|str| throw(&str))
        .map(move |files_content| Snapshot::store_files_content(&context, &files_content))
    })
    .to_boxed()
}

fn directory_with_prefix_to_strip_to_digest(context: Context, request: Value) -> NodeFuture<Value> {
  let core = context.core;

  Box::pin(async move {
    let input_digest = lift_digest(&externs::project_ignoring_type(
      &request,
      "directory_digest",
    ))?;
    let prefix = externs::project_str(&request, "prefix");
    let digest =
      store::Snapshot::strip_prefix(core.store(), input_digest, PathBuf::from(prefix)).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&core, &digest));
    res
  })
  .compat()
  .map_err(|e: String| throw(&e))
  .to_boxed()
}

fn directory_with_prefix_to_add_to_digest(context: Context, request: Value) -> NodeFuture<Value> {
  let core = context.core;
  Box::pin(async move {
    let input_digest = lift_digest(&externs::project_ignoring_type(
      &request,
      "directory_digest",
    ))?;

    let prefix = externs::project_str(&request, "prefix");
    let digest =
      store::Snapshot::add_prefix(core.store(), input_digest, PathBuf::from(prefix)).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&core, &digest));
    res
  })
  .compat()
  .map_err(|e: String| throw(&e))
  .to_boxed()
}

fn digest_to_snapshot(context: Context, directory_digest_val: Value) -> NodeFuture<Value> {
  let core = context.core.clone();
  let store = context.core.store();
  Box::pin(async move {
    let digest = lift_digest(&directory_digest_val)?;
    let snapshot = store::Snapshot::from_digest(store, digest).await?;
    let res: Result<_, String> = Ok(Snapshot::store_snapshot(&core, &snapshot));
    res
  })
  .compat()
  .map_err(|e: String| throw(&e))
  .to_boxed()
}

fn directories_to_merge_to_digest(context: Context, request: Value) -> NodeFuture<Value> {
  let core = context.core;
  let digests: Result<Vec<hashing::Digest>, String> =
    externs::project_multi(&request, "directories")
      .into_iter()
      .map(|val| lift_digest(&val))
      .collect();
  Box::pin(async move {
    let digest = store::Snapshot::merge_directories(core.store(), digests?).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&core, &digest));
    res
  })
  .compat()
  .map_err(|err: String| throw(&err))
  .to_boxed()
}

fn url_to_fetch_to_snapshot(context: Context, val: Value) -> NodeFuture<Value> {
  let core = context.core.clone();
  context
    .get(DownloadedFile(externs::key_for(val)))
    .map(move |snapshot| Snapshot::store_snapshot(&core, &snapshot))
    .to_boxed()
}

fn path_globs_to_snapshot(context: Context, val: Value) -> NodeFuture<Value> {
  let core = context.core.clone();
  context
    .get(Snapshot(externs::key_for(val)))
    .map(move |snapshot| Snapshot::store_snapshot(&core, &snapshot))
    .to_boxed()
}

fn input_files_content_to_digest(context: Context, files_content: Value) -> NodeFuture<Value> {
  let file_values = externs::project_multi(&files_content, "dependencies");
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

  Box::pin(async move {
    let digests = future03::try_join_all(digests).await?;
    let digest = store::Snapshot::merge_directories(context.core.store(), digests).await?;
    let res: Result<_, String> = Ok(Snapshot::store_directory(&context.core, &digest));
    res
  })
  .compat()
  .map_err(|err: String| throw(&err))
  .to_boxed()
}

fn snapshot_subset_to_snapshot(context: Context, value: Value) -> NodeFuture<Value> {
  let globs = externs::project_ignoring_type(&value, "globs");
  let store = context.core.store();

  Box::pin(async move {
    let path_globs = Snapshot::lift_path_globs(&globs)?;
    let original_digest = lift_digest(&externs::project_ignoring_type(&value, "directory_digest"))?;

    let snapshot = store::Snapshot::get_snapshot_subset(store, original_digest, path_globs).await?;

    Ok(Snapshot::store_snapshot(&context.core, &snapshot))
  })
  .compat()
  .map_err(|err: String| throw(&err))
  .to_boxed()
}
