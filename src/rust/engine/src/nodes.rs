// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashMap};
use std::convert::TryFrom;
use std::fmt::Display;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use std::{self, fmt};

use async_trait::async_trait;
use futures::future::{self, FutureExt, TryFutureExt};
use futures::stream::StreamExt;
use std::convert::TryInto;
use url::Url;

use crate::context::{Context, Core};
use crate::core::{throw, Failure, Key, Params, TypeId, Value};
use crate::externs;
use crate::selectors;
use crate::tasks::{self, Rule};
use boxfuture::{BoxFuture, Boxable};
use bytes::{self, BufMut};
use cpython::Python;
use fs::{
  self, Dir, DirectoryListing, File, FileContent, GlobExpansionConjunction, GlobMatching, Link,
  PathGlobs, PathStat, PreparedPathGlobs, StrictGlobMatching, VFS,
};
use logging::PythonLogLevel;
use process_execution::{
  self, CacheDest, CacheName, MultiPlatformProcess, PlatformConstraint, Process, RelativePath,
};

use graph::{Entry, Node, NodeError, NodeVisualizer};
use store::{self, StoreFileByDigest};
use workunit_store::{new_span_id, scope_task_workunit_state, Level, WorkunitMetadata};

pub type NodeResult<T> = Result<T, Failure>;

#[async_trait]
impl VFS<Failure> for Context {
  async fn read_link(&self, link: &Link) -> Result<PathBuf, Failure> {
    Ok(self.get(ReadLink(link.clone())).await?.0)
  }

  async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, Failure> {
    self.get(Scandir(dir)).await
  }

  fn is_ignored(&self, stat: &fs::Stat) -> bool {
    self.core.vfs.is_ignored(stat)
  }

  fn mk_error(msg: &str) -> Failure {
    throw(msg)
  }
}

impl StoreFileByDigest<Failure> for Context {
  fn store_by_digest(&self, file: File) -> BoxFuture<hashing::Digest, Failure> {
    let context = self.clone();
    async move { context.get(DigestFile(file)).await }
      .boxed()
      .compat()
      .to_boxed()
  }
}

///
/// A simplified implementation of graph::Node for members of the NodeKey enum to implement.
/// NodeKey's impl of graph::Node handles the rest.
///
/// The Item type of a WrappedNode is bounded to values that can be stored and retrieved
/// from the NodeOutput enum. Due to the semantics of memoization, retrieving the typed result
/// stored inside the NodeOutput requires an implementation of TryFrom<NodeOutput>. But the
/// combination of bounds at usage sites should mean that a failure to unwrap the result is
/// exceedingly rare.
///
#[async_trait]
pub trait WrappedNode: Into<NodeKey> {
  type Item: TryFrom<NodeOutput>;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Self::Item>;
}

///
/// A Node that selects a product for some Params.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub params: Params,
  pub product: TypeId,
  entry: rule_graph::Entry<Rule>,
}

impl Select {
  pub fn new(mut params: Params, product: TypeId, entry: rule_graph::Entry<Rule>) -> Select {
    params.retain(|k| match &entry {
      &rule_graph::Entry::Param(ref type_id) => type_id == k.type_id(),
      &rule_graph::Entry::WithDeps(ref with_deps) => with_deps.params().contains(k.type_id()),
    });
    Select {
      params,
      product,
      entry,
    }
  }

  pub fn new_from_edges(
    params: Params,
    product: TypeId,
    edges: &rule_graph::RuleEdges<Rule>,
  ) -> Select {
    let dependency_key = selectors::DependencyKey::JustSelect(selectors::Select::new(product));
    // TODO: Is it worth propagating an error here?
    let entry = edges
      .entry_for(&dependency_key)
      .unwrap_or_else(|| panic!("{:?} did not declare a dependency on {:?}", edges, product))
      .clone();
    Select::new(params, product, entry)
  }

  async fn select_product(
    &self,
    context: &Context,
    product: TypeId,
    caller_description: &str,
  ) -> NodeResult<Value> {
    let edges = context
      .core
      .rule_graph
      .edges_for_inner(&self.entry)
      .ok_or_else(|| {
        throw(&format!(
          "Tried to select product {} for {} but found no edges",
          product, caller_description
        ))
      })?;
    let context = context.clone();
    Select::new_from_edges(self.params.clone(), product, &edges)
      .run_wrapped_node(context)
      .await
  }
}

// TODO: This is a Node only because it is used as a root in the graph, but it should never be
// requested using context.get
#[async_trait]
impl WrappedNode for Select {
  type Item = Value;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Value> {
    match &self.entry {
      &rule_graph::Entry::WithDeps(rule_graph::EntryWithDeps::Inner(ref inner)) => {
        match inner.rule() {
          &tasks::Rule::Task(ref task) => context
            .get(Task {
              params: self.params.clone(),
              product: self.product,
              task: task.clone(),
              entry: Arc::new(self.entry.clone()),
            })
            .await
            .map(|(v, _)| v),
          &Rule::Intrinsic(ref intrinsic) => {
            let intrinsic = intrinsic.clone();
            let values = future::try_join_all(
              intrinsic
                .inputs
                .iter()
                .map(|type_id| self.select_product(&context, *type_id, "intrinsic"))
                .collect::<Vec<_>>(),
            )
            .await?;
            context
              .core
              .intrinsics
              .run(intrinsic, context.clone(), values)
              .await
          }
        }
      }
      &rule_graph::Entry::Param(type_id) => {
        if let Some(key) = self.params.find(type_id) {
          Ok(externs::val_for(key))
        } else {
          Err(throw(&format!(
            "Expected a Param of type {} to be present.",
            type_id
          )))
        }
      }
      &rule_graph::Entry::WithDeps(rule_graph::EntryWithDeps::Root(_)) => {
        panic!("Not a runtime-executable entry! {:?}", self.entry)
      }
    }
  }
}

impl From<Select> for NodeKey {
  fn from(n: Select) -> Self {
    NodeKey::Select(Box::new(n))
  }
}

pub fn lift_digest(digest: &Value) -> Result<hashing::Digest, String> {
  let fingerprint = externs::project_str(&digest, "fingerprint");
  let digest_length = externs::project_u64(&digest, "serialized_bytes_length") as usize;
  Ok(hashing::Digest(
    hashing::Fingerprint::from_hex_string(&fingerprint)?,
    digest_length,
  ))
}

/// A Node that represents a set of processes to execute on specific platforms.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct MultiPlatformExecuteProcess(MultiPlatformProcess);

impl MultiPlatformExecuteProcess {
  fn lift_execute_process(
    value: &Value,
    target_platform: PlatformConstraint,
  ) -> Result<Process, String> {
    let env = externs::project_tuple_encoded_map(&value, "env")?;

    let working_directory = {
      let val = externs::project_str(&value, "working_directory");
      if val.is_empty() {
        None
      } else {
        Some(RelativePath::new(val.as_str())?)
      }
    };

    let digest = lift_digest(&externs::project_ignoring_type(&value, "input_digest"))
      .map_err(|err| format!("Error parsing digest {}", err))?;

    let output_files = externs::project_multi_strs(&value, "output_files")
      .into_iter()
      .map(PathBuf::from)
      .collect();

    let output_directories = externs::project_multi_strs(&value, "output_directories")
      .into_iter()
      .map(PathBuf::from)
      .collect();

    let timeout_in_seconds = externs::project_f64(&value, "timeout_seconds");

    let timeout = if timeout_in_seconds < 0.0 {
      None
    } else {
      Some(Duration::from_millis((timeout_in_seconds * 1000.0) as u64))
    };

    let description = externs::project_str(&value, "description");

    let append_only_caches = externs::project_tuple_encoded_map(&value, "append_only_caches")?
      .into_iter()
      .map(|(name, dest)| Ok((CacheName::new(name)?, CacheDest::new(dest)?)))
      .collect::<Result<_, String>>()?;

    let jdk_home = {
      let val = externs::project_str(&value, "jdk_home");
      if val.is_empty() {
        None
      } else {
        Some(PathBuf::from(val))
      }
    };

    let is_nailgunnable = externs::project_bool(&value, "is_nailgunnable");

    Ok(process_execution::Process {
      argv: externs::project_multi_strs(&value, "argv"),
      env,
      working_directory,
      input_files: digest,
      output_files,
      output_directories,
      timeout,
      description,
      append_only_caches,
      jdk_home,
      target_platform,
      is_nailgunnable,
    })
  }

  pub fn lift(value: &Value) -> Result<MultiPlatformExecuteProcess, String> {
    let constraint_parts = externs::project_multi_strs(&value, "platform_constraints");
    if constraint_parts.len() % 2 != 0 {
      return Err("Error parsing platform_constraints: odd number of parts".to_owned());
    }
    let constraint_key_pairs: Vec<_> = constraint_parts
      .chunks_exact(2)
      .map(|constraint_key_pair| {
        (
          PlatformConstraint::try_from(&constraint_key_pair[0]).unwrap(),
          PlatformConstraint::try_from(&constraint_key_pair[1]).unwrap(),
        )
      })
      .collect();
    let processes = externs::project_multi(&value, "processes");
    if constraint_parts.len() / 2 != processes.len() {
      return Err(format!(
        "Sizes of constraint keys and processes do not match: {} vs. {}",
        constraint_parts.len() / 2,
        processes.len()
      ));
    }

    let mut request_by_constraint: BTreeMap<(PlatformConstraint, PlatformConstraint), Process> =
      BTreeMap::new();
    for (constraint_key, execute_process) in constraint_key_pairs.iter().zip(processes.iter()) {
      let underlying_req =
        MultiPlatformExecuteProcess::lift_execute_process(execute_process, constraint_key.1)?;
      request_by_constraint.insert(*constraint_key, underlying_req.clone());
    }
    Ok(MultiPlatformExecuteProcess(MultiPlatformProcess(
      request_by_constraint,
    )))
  }
}

impl From<MultiPlatformExecuteProcess> for NodeKey {
  fn from(n: MultiPlatformExecuteProcess) -> Self {
    NodeKey::MultiPlatformExecuteProcess(Box::new(n))
  }
}

#[async_trait]
impl WrappedNode for MultiPlatformExecuteProcess {
  type Item = ProcessResult;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<ProcessResult> {
    let request = self.0;
    let execution_context = process_execution::Context::new(
      context.session.workunit_store(),
      context.session.build_id().to_string(),
    );
    if context
      .core
      .command_runner
      .extract_compatible_request(&request)
      .is_some()
    {
      let res = context
        .core
        .command_runner
        .run(request, execution_context)
        .await
        .map_err(|e| throw(&format!("Failed to execute process: {}", e)))?;

      Ok(ProcessResult(res))
    } else {
      Err(throw(&format!(
        "No compatible platform found for request: {:?}",
        request
      )))
    }
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcessResult(pub process_execution::FallibleProcessResultWithPlatform);

///
/// A Node that represents reading the destination of a symlink (non-recursively).
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ReadLink(Link);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LinkDest(PathBuf);

#[async_trait]
impl WrappedNode for ReadLink {
  type Item = LinkDest;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<LinkDest> {
    let node = self;
    let link_dest = context
      .core
      .vfs
      .read_link(&node.0)
      .await
      .map_err(|e| throw(&format!("{}", e)))?;
    Ok(LinkDest(link_dest))
  }
}

impl From<ReadLink> for NodeKey {
  fn from(n: ReadLink) -> Self {
    NodeKey::ReadLink(n)
  }
}

///
/// A Node that represents reading a file and fingerprinting its contents.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct DigestFile(pub File);

#[async_trait]
impl WrappedNode for DigestFile {
  type Item = hashing::Digest;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<hashing::Digest> {
    let content = context
      .core
      .vfs
      .read_file(&self.0)
      .map_err(|e| throw(&format!("{}", e)))
      .await?;
    context
      .core
      .store()
      .store_file_bytes(content.content, true)
      .map_err(|e| throw(&e))
      .await
  }
}

impl From<DigestFile> for NodeKey {
  fn from(n: DigestFile) -> Self {
    NodeKey::DigestFile(n)
  }
}

///
/// A Node that represents executing a directory listing that returns a Stat per directory
/// entry (generally in one syscall). No symlinks are expanded.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Scandir(Dir);

#[async_trait]
impl WrappedNode for Scandir {
  type Item = Arc<DirectoryListing>;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Arc<DirectoryListing>> {
    let directory_listing = context
      .core
      .vfs
      .scandir(self.0)
      .await
      .map_err(|e| throw(&format!("{}", e)))?;
    Ok(Arc::new(directory_listing))
  }
}

impl From<Scandir> for NodeKey {
  fn from(n: Scandir) -> Self {
    NodeKey::Scandir(n)
  }
}

///
/// A Node that captures an store::Snapshot for a PathGlobs subject.
///
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Snapshot(pub Key);

impl Snapshot {
  async fn create(context: Context, path_globs: PreparedPathGlobs) -> NodeResult<store::Snapshot> {
    // Recursively expand PathGlobs into PathStats.
    // We rely on Context::expand tracking dependencies for scandirs,
    // and store::Snapshot::from_path_stats tracking dependencies for file digests.
    let path_stats = context
      .expand(path_globs)
      .map_err(|e| throw(&format!("{}", e)))
      .await?;
    store::Snapshot::from_path_stats(context.core.store(), context.clone(), path_stats)
      .map_err(|e| throw(&format!("Snapshot failed: {}", e)))
      .await
  }

  pub fn lift_path_globs(item: &Value) -> Result<PreparedPathGlobs, String> {
    let globs = externs::project_multi_strs(item, "globs");

    let description_of_origin_field = externs::project_str(item, "description_of_origin");
    let description_of_origin = if description_of_origin_field.is_empty() {
      None
    } else {
      Some(description_of_origin_field)
    };

    let glob_match_error_behavior =
      externs::project_ignoring_type(item, "glob_match_error_behavior");
    let failure_behavior = externs::project_str(&glob_match_error_behavior, "value");
    let strict_glob_matching =
      StrictGlobMatching::create(failure_behavior.as_str(), description_of_origin)?;

    let conjunction_obj = externs::project_ignoring_type(item, "conjunction");
    let conjunction_string = externs::project_str(&conjunction_obj, "value");
    let conjunction = GlobExpansionConjunction::create(&conjunction_string)?;

    PathGlobs::new(globs.clone(), strict_glob_matching, conjunction)
      .parse()
      .map_err(|e| format!("Failed to parse PathGlobs for globs({:?}): {}", globs, e))
  }

  pub fn store_directory(core: &Arc<Core>, item: &hashing::Digest) -> Value {
    externs::unsafe_call(
      &core.types.construct_directory_digest,
      &[
        externs::store_utf8(&item.0.to_hex()),
        externs::store_i64(item.1 as i64),
      ],
    )
  }

  pub fn store_snapshot(core: &Arc<Core>, item: &store::Snapshot) -> Result<Value, String> {
    let mut files = Vec::new();
    let mut dirs = Vec::new();
    for ps in &item.path_stats {
      match ps {
        &PathStat::File { ref path, .. } => {
          files.push(Self::store_path(path)?);
        }
        &PathStat::Dir { ref path, .. } => {
          dirs.push(Self::store_path(path)?);
        }
      }
    }
    Ok(externs::unsafe_call(
      &core.types.construct_snapshot,
      &[
        Self::store_directory(core, &item.digest),
        externs::store_tuple(files),
        externs::store_tuple(dirs),
      ],
    ))
  }

  fn store_path(item: &Path) -> Result<Value, String> {
    if let Some(p) = item.as_os_str().to_str() {
      Ok(externs::store_utf8(p))
    } else {
      Err(format!("Could not decode path `{:?}` as UTF8.", item))
    }
  }

  fn store_file_content(context: &Context, item: &FileContent) -> Result<Value, String> {
    Ok(externs::unsafe_call(
      &context.core.types.construct_file_content,
      &[
        Self::store_path(&item.path)?,
        externs::store_bytes(&item.content),
        externs::store_bool(item.is_executable),
      ],
    ))
  }

  pub fn store_files_content(context: &Context, item: &[FileContent]) -> Result<Value, String> {
    let entries = item
      .iter()
      .map(|e| Self::store_file_content(context, e))
      .collect::<Result<Vec<_>, _>>()?;
    Ok(externs::unsafe_call(
      &context.core.types.construct_files_content,
      &[externs::store_tuple(entries)],
    ))
  }
}

#[async_trait]
impl WrappedNode for Snapshot {
  type Item = Arc<store::Snapshot>;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Arc<store::Snapshot>> {
    let path_globs = Self::lift_path_globs(&externs::val_for(&self.0))
      .map_err(|e| throw(&format!("Failed to parse PathGlobs: {}", e)))?;
    let snapshot = Self::create(context, path_globs).await?;
    Ok(Arc::new(snapshot))
  }
}

impl From<Snapshot> for NodeKey {
  fn from(n: Snapshot) -> Self {
    NodeKey::Snapshot(n)
  }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct DownloadedFile(pub Key);

impl DownloadedFile {
  async fn load_or_download(
    &self,
    core: Arc<Core>,
    url: Url,
    digest: hashing::Digest,
  ) -> Result<store::Snapshot, String> {
    let file_name = url
      .path_segments()
      .and_then(Iterator::last)
      .map(str::to_owned)
      .ok_or_else(|| format!("Error getting the file name from the parsed URL: {}", url))?;

    let maybe_bytes = core.store().load_file_bytes_with(digest, |_| ()).await?;
    if maybe_bytes.is_none() {
      DownloadedFile::download(core.clone(), url, file_name.clone(), digest).await?;
    }
    core
      .store()
      .snapshot_of_one_file(PathBuf::from(file_name), digest, true)
      .await
  }

  async fn download(
    core: Arc<Core>,
    url: Url,
    file_name: String,
    expected_digest: hashing::Digest,
  ) -> Result<(), String> {
    // TODO: Retry failures
    let response = core
      .http_client
      .get(url.clone())
      .send()
      .await
      .map_err(|err| format!("Error downloading file: {}", err))?;

    // Handle common HTTP errors.
    if response.status().is_server_error() {
      return Err(format!(
        "Server error ({}) downloading file {} from {}",
        response.status().as_str(),
        file_name,
        url,
      ));
    } else if response.status().is_client_error() {
      return Err(format!(
        "Client error ({}) downloading file {} from {}",
        response.status().as_str(),
        file_name,
        url,
      ));
    }

    let (actual_digest, bytes) = {
      struct SizeLimiter<W: std::io::Write> {
        writer: W,
        written: usize,
        size_limit: usize,
      }

      impl<W: std::io::Write> Write for SizeLimiter<W> {
        fn write(&mut self, buf: &[u8]) -> Result<usize, std::io::Error> {
          let new_size = self.written + buf.len();
          if new_size > self.size_limit {
            Err(std::io::Error::new(
              std::io::ErrorKind::InvalidData,
              "Downloaded file was larger than expected digest",
            ))
          } else {
            self.written = new_size;
            self.writer.write_all(buf)?;
            Ok(buf.len())
          }
        }

        fn flush(&mut self) -> Result<(), std::io::Error> {
          self.writer.flush()
        }
      }

      let mut hasher = hashing::WriterHasher::new(SizeLimiter {
        writer: bytes::BytesMut::with_capacity(expected_digest.1).writer(),
        written: 0,
        size_limit: expected_digest.1,
      });

      let mut response_stream = response.bytes_stream();
      while let Some(next_chunk) = response_stream.next().await {
        let chunk =
          next_chunk.map_err(|err| format!("Error reading URL fetch response: {}", err))?;
        hasher
          .write_all(&chunk)
          .map_err(|err| format!("Error hashing/capturing URL fetch response: {}", err))?;
      }
      let (digest, bytewriter) = hasher.finish();
      (digest, bytewriter.writer.into_inner().freeze())
    };

    if expected_digest != actual_digest {
      return Err(format!(
        "Wrong digest for downloaded file: want {:?} got {:?}",
        expected_digest, actual_digest
      ));
    }

    let _ = core.store().store_file_bytes(bytes, true).await?;
    Ok(())
  }
}

#[async_trait]
impl WrappedNode for DownloadedFile {
  type Item = Arc<store::Snapshot>;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Arc<store::Snapshot>> {
    let value = externs::val_for(&self.0);
    let url_to_fetch = externs::project_str(&value, "url");

    let url = Url::parse(&url_to_fetch)
      .map_err(|err| throw(&format!("Error parsing URL {}: {}", url_to_fetch, err)))?;

    let expected_digest =
      lift_digest(&externs::project_ignoring_type(&value, "digest")).map_err(|s| throw(&s))?;

    let snapshot = self
      .load_or_download(context.core, url, expected_digest)
      .await
      .map_err(|err| throw(&err))?;
    Ok(Arc::new(snapshot))
  }
}

impl From<DownloadedFile> for NodeKey {
  fn from(n: DownloadedFile) -> Self {
    NodeKey::DownloadedFile(n)
  }
}

#[derive(Clone, Eq, Hash, PartialEq)]
pub struct Task {
  params: Params,
  product: TypeId,
  task: tasks::Task,
  entry: Arc<rule_graph::Entry<Rule>>,
}

impl Task {
  async fn gen_get(
    context: &Context,
    params: &Params,
    entry: &Arc<rule_graph::Entry<Rule>>,
    gets: Vec<externs::Get>,
  ) -> NodeResult<Vec<Value>> {
    let get_futures = gets
      .into_iter()
      .map(|get| {
        let context = context.clone();
        let mut params = params.clone();
        let entry = entry.clone();
        let dependency_key = selectors::DependencyKey::JustGet(selectors::Get {
          product: get.product,
          subject: *get.subject.type_id(),
        });
        let entry_res = context
          .core
          .rule_graph
          .edges_for_inner(&entry)
          .ok_or_else(|| throw(&format!("no edges for task {:?} exist!", entry)))
          .and_then(|edges| {
            edges
              .entry_for(&dependency_key)
              .cloned()
              .ok_or_else(|| match get.declared_subject {
                Some(ty) if externs::is_union(ty) => {
                  let value = externs::get_value_from_type_id(ty);
                  match externs::call_method(
                    &value,
                    "non_member_error_message",
                    &[externs::val_for(&get.subject)],
                  ) {
                    Ok(err_msg) => throw(&externs::val_to_str(&err_msg)),
                    // If the non_member_error_message() call failed for any reason,
                    // fall back to a generic message.
                    Err(_e) => throw(&format!(
                      "Type {} is not a member of the {} @union",
                      get.subject.type_id(),
                      ty
                    )),
                  }
                }
                _ => throw(&format!(
                  "{:?} did not declare a dependency on {:?}",
                  entry, dependency_key
                )),
              })
          });
        // The subject of the get is a new parameter that replaces an existing param of the same
        // type.
        params.put(get.subject);
        async move {
          let entry = entry_res?;
          Select::new(params, get.product, entry)
            .run_wrapped_node(context.clone())
            .await
        }
      })
      .collect::<Vec<_>>();
    future::try_join_all(get_futures).await
  }

  fn compute_new_workunit_level(
    can_modify_workunit: bool,
    result_val: &Value,
  ) -> Option<log::Level> {
    use num_enum::TryFromPrimitiveError;

    if !can_modify_workunit {
      return None;
    }

    let new_level_val: Value = externs::call_method(&result_val, "level", &[]).ok()?;

    {
      let gil = Python::acquire_gil();
      let py = gil.python();

      if *new_level_val == py.None() {
        return None;
      }
    }

    let new_py_level: PythonLogLevel = match externs::project_maybe_u64(&new_level_val, "_level")
      .and_then(|n: u64| {
        n.try_into()
          .map_err(|e: TryFromPrimitiveError<_>| e.to_string())
      }) {
      Ok(level) => level,
      Err(e) => {
        log::warn!("Couldn't parse {:?} as a LogLevel: {}", new_level_val, e);
        return None;
      }
    };

    Some(new_py_level.into())
  }

  ///
  /// Given a python generator Value, loop to request the generator's dependencies until
  /// it completes with a result Value.
  ///
  async fn generate(
    context: Context,
    params: Params,
    entry: Arc<rule_graph::Entry<Rule>>,
    generator: Value,
  ) -> NodeResult<Value> {
    let mut input = Value::from(externs::none());
    loop {
      let context = context.clone();
      let params = params.clone();
      let entry = entry.clone();
      match externs::generator_send(&generator, &input)? {
        externs::GeneratorResponse::Get(get) => {
          let values = Self::gen_get(&context, &params, &entry, vec![get]).await?;
          input = values.into_iter().next().unwrap();
        }
        externs::GeneratorResponse::GetMulti(gets) => {
          let values = Self::gen_get(&context, &params, &entry, gets).await?;
          input = externs::store_tuple(values);
        }
        externs::GeneratorResponse::Break(val) => {
          break Ok(val);
        }
      }
    }
  }
}

impl fmt::Debug for Task {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(
      f,
      "Task({}, {}, {}, {})",
      self.task.func, self.params, self.product, self.task.cacheable,
    )
  }
}

#[async_trait]
impl WrappedNode for Task {
  type Item = (Value, Option<log::Level>);

  async fn run_wrapped_node(self, context: Context) -> NodeResult<(Value, Option<log::Level>)> {
    let params = self.params;
    let deps = {
      let edges = &context
        .core
        .rule_graph
        .edges_for_inner(&self.entry)
        .expect("edges for task exist.");
      future::try_join_all(
        self
          .task
          .clause
          .into_iter()
          .map(|type_id| {
            Select::new_from_edges(params.clone(), type_id, edges).run_wrapped_node(context.clone())
          })
          .collect::<Vec<_>>(),
      )
      .await?
    };

    let func = self.task.func;
    let entry = self.entry;
    let product = self.product;
    let can_modify_workunit = self.task.can_modify_workunit;

    let mut result_val = externs::call(&externs::val_for(&func.0), &deps)?;
    let mut result_type = externs::get_type_for(&result_val);
    if result_type == context.core.types.coroutine {
      result_val = Self::generate(context, params, entry, result_val).await?;
      result_type = externs::get_type_for(&result_val);
    }

    if result_type == product {
      let maybe_new_level = Self::compute_new_workunit_level(can_modify_workunit, &result_val);
      Ok((result_val, maybe_new_level))
    } else {
      Err(throw(&format!(
        "{:?} returned a result value that did not satisfy its constraints: {:?}",
        func, result_val
      )))
    }
  }
}

impl From<Task> for NodeKey {
  fn from(n: Task) -> Self {
    NodeKey::Task(Box::new(n))
  }
}

#[derive(Default)]
pub struct Visualizer {
  viz_colors: HashMap<String, String>,
}

impl NodeVisualizer<NodeKey> for Visualizer {
  fn color_scheme(&self) -> &str {
    "set312"
  }

  fn color(&mut self, entry: &Entry<NodeKey>, context: &<NodeKey as Node>::Context) -> String {
    let max_colors = 12;
    match entry.peek(context) {
      None => "white".to_string(),
      Some(_) => {
        let viz_colors_len = self.viz_colors.len();
        self
          .viz_colors
          .entry(entry.node().product_str())
          .or_insert_with(|| format!("{}", viz_colors_len % max_colors + 1))
          .clone()
      }
    }
  }
}

///
/// There is large variance in the sizes of the members of this enum, so a few of them are boxed.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum NodeKey {
  DigestFile(DigestFile),
  DownloadedFile(DownloadedFile),
  MultiPlatformExecuteProcess(Box<MultiPlatformExecuteProcess>),
  ReadLink(ReadLink),
  Scandir(Scandir),
  Select(Box<Select>),
  Snapshot(Snapshot),
  Task(Box<Task>),
}

impl NodeKey {
  fn product_str(&self) -> String {
    match self {
      &NodeKey::MultiPlatformExecuteProcess(..) => "ProcessResult".to_string(),
      &NodeKey::DownloadedFile(..) => "DownloadedFile".to_string(),
      &NodeKey::Select(ref s) => format!("{}", s.product),
      &NodeKey::Task(ref s) => format!("{}", s.product),
      &NodeKey::Snapshot(..) => "Snapshot".to_string(),
      &NodeKey::DigestFile(..) => "DigestFile".to_string(),
      &NodeKey::ReadLink(..) => "LinkDest".to_string(),
      &NodeKey::Scandir(..) => "DirectoryListing".to_string(),
    }
  }

  pub fn fs_subject(&self) -> Option<&Path> {
    match self {
      &NodeKey::DigestFile(ref s) => Some(s.0.path.as_path()),
      &NodeKey::ReadLink(ref s) => Some((s.0).0.as_path()),
      &NodeKey::Scandir(ref s) => Some((s.0).0.as_path()),

      // Not FS operations:
      // Explicitly listed so that if people add new NodeKeys they need to consider whether their
      // NodeKey represents an FS operation, and accordingly whether they need to add it to the
      // above list or the below list.
      &NodeKey::MultiPlatformExecuteProcess { .. }
      | &NodeKey::Select { .. }
      | &NodeKey::Snapshot { .. }
      | &NodeKey::Task { .. }
      | &NodeKey::DownloadedFile { .. } => None,
    }
  }

  fn workunit_level(&self) -> Level {
    match self {
      NodeKey::Task(ref task) => task.task.display_info.level,
      _ => Level::Debug,
    }
  }

  ///
  /// Provides the `name` field in workunits associated with this node. These names
  /// should be friendly to machine-parsing (i.e. "my_node" rather than "My awesome node!").
  ///
  fn workunit_name(&self) -> String {
    match self {
      NodeKey::Task(ref task) => task.task.display_info.name.clone(),
      NodeKey::MultiPlatformExecuteProcess(mp_epr) => mp_epr.0.workunit_name(),
      NodeKey::Snapshot(..) => "snapshot".to_string(),
      NodeKey::DigestFile(..) => "digest_file".to_string(),
      NodeKey::DownloadedFile(..) => "downloaded_file".to_string(),
      NodeKey::ReadLink(..) => "read_link".to_string(),
      NodeKey::Scandir(_) => "scandir".to_string(),
      NodeKey::Select(..) => "select".to_string(),
    }
  }

  ///
  /// Nodes optionally have a user-facing name (distinct from their Debug and Display
  /// implementations). This user-facing name is intended to provide high-level information
  /// to end users of pants about what computation pants is currently doing. Not all
  /// `Node`s need a user-facing name. For `Node`s derived from Python `@rule`s, the
  /// user-facing name should be the same as the `desc` annotation on the rule decorator.
  ///
  fn user_facing_name(&self) -> Option<String> {
    match self {
      NodeKey::Task(ref task) => task.task.display_info.desc.as_ref().map(|s| s.to_owned()),
      NodeKey::Snapshot(_) => Some(format!("{}", self)),
      NodeKey::MultiPlatformExecuteProcess(mp_epr) => mp_epr.0.user_facing_name(),
      NodeKey::DigestFile(DigestFile(File { path, .. })) => {
        Some(format!("Fingerprinting: {}", path.display()))
      }
      NodeKey::DownloadedFile(..) => None,
      NodeKey::ReadLink(..) => None,
      NodeKey::Scandir(Scandir(Dir(path))) => Some(format!("Reading {}", path.display())),
      NodeKey::Select(..) => None,
    }
  }
}

#[async_trait]
impl Node for NodeKey {
  type Context = Context;

  type Item = NodeOutput;
  type Error = Failure;

  async fn run(self, context: Context) -> Result<NodeOutput, Failure> {
    let mut workunit_state = workunit_store::expect_workunit_state();

    let (started_workunit_id, user_facing_name, metadata) = {
      let user_facing_name = self.user_facing_name();
      let name = self.workunit_name();
      let span_id = new_span_id();

      // We're starting a new workunit: record our parent, and set the current parent to our span.
      let parent_id = std::mem::replace(&mut workunit_state.parent_id, Some(span_id.clone()));
      let metadata = WorkunitMetadata {
        desc: user_facing_name.clone(),
        level: self.workunit_level(),
        blocked: false,
        stdout: None,
        stderr: None,
      };

      let started_workunit_id =
        context
          .session
          .workunit_store()
          .start_workunit(span_id, name, parent_id, metadata.clone());
      (started_workunit_id, user_facing_name, metadata)
    };

    scope_task_workunit_state(Some(workunit_state), async move {
      let context2 = context.clone();
      let maybe_watch = if let Some(path) = self.fs_subject() {
        let abs_path = context.core.build_root.join(path);
        context
          .core
          .watcher
          .watch(abs_path)
          .map_err(|e| Context::mk_error(&format!("{:?}", e)))
          .await
      } else {
        Ok(())
      };

      let mut level = metadata.level;
      let mut result = match maybe_watch {
        Ok(()) => match self {
          NodeKey::DigestFile(n) => n.run_wrapped_node(context).map_ok(NodeOutput::Digest).await,
          NodeKey::DownloadedFile(n) => {
            n.run_wrapped_node(context)
              .map_ok(NodeOutput::Snapshot)
              .await
          }
          NodeKey::MultiPlatformExecuteProcess(n) => {
            n.run_wrapped_node(context)
              .map_ok(|r| NodeOutput::ProcessResult(Box::new(r)))
              .await
          }
          NodeKey::ReadLink(n) => {
            n.run_wrapped_node(context)
              .map_ok(NodeOutput::LinkDest)
              .await
          }
          NodeKey::Scandir(n) => {
            n.run_wrapped_node(context)
              .map_ok(NodeOutput::DirectoryListing)
              .await
          }
          NodeKey::Select(n) => n.run_wrapped_node(context).map_ok(NodeOutput::Value).await,
          NodeKey::Snapshot(n) => {
            n.run_wrapped_node(context)
              .map_ok(NodeOutput::Snapshot)
              .await
          }
          NodeKey::Task(n) => {
            n.run_wrapped_node(context)
              .map_ok(|(v, maybe_new_level)| {
                if let Some(new_level) = maybe_new_level {
                  level = new_level;
                }
                NodeOutput::Value(v)
              })
              .await
          }
        },
        Err(e) => Err(e),
      };

      if let Some(user_facing_name) = user_facing_name {
        result = result.map_err(|failure| failure.with_pushed_frame(&user_facing_name));
      }

      let final_metadata = WorkunitMetadata { level, ..metadata };
      context2
        .session
        .workunit_store()
        .complete_workunit_with_new_metadata(started_workunit_id, final_metadata)
        .unwrap();
      result
    })
    .await
  }

  fn cacheable(&self) -> bool {
    match self {
      &NodeKey::Task(ref s) => s.task.cacheable,
      _ => true,
    }
  }
}

impl Display for NodeKey {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    match self {
      &NodeKey::DigestFile(ref s) => write!(f, "DigestFile({:?})", s.0),
      &NodeKey::DownloadedFile(ref s) => write!(f, "DownloadedFile({:?})", s.0),
      &NodeKey::MultiPlatformExecuteProcess(ref s) => {
        write!(f, "MultiPlatformExecuteProcess({:?}", s.0)
      }
      &NodeKey::ReadLink(ref s) => write!(f, "ReadLink({:?})", s.0),
      &NodeKey::Scandir(ref s) => write!(f, "Scandir({:?})", s.0),
      &NodeKey::Select(ref s) => write!(f, "Select({}, {})", s.params, s.product,),
      &NodeKey::Task(ref task) => write!(f, "{:?}", task),
      &NodeKey::Snapshot(ref s) => write!(f, "Snapshot({})", format!("{}", &s.0)),
    }
  }
}

impl NodeError for Failure {
  fn invalidated() -> Failure {
    Failure::Invalidated
  }

  fn exhausted() -> Failure {
    Context::mk_error("Exhausted retries while waiting for the filesystem to stabilize.")
  }

  fn cyclic(mut path: Vec<String>) -> Failure {
    let path_len = path.len();
    if path_len > 1 {
      path[0] += " <-";
      path[path_len - 1] += " <-"
    }
    throw(&format!(
      "Dependency graph contained a cycle:\n  {}",
      path.join("\n  ")
    ))
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NodeOutput {
  Digest(hashing::Digest),
  DirectoryListing(Arc<DirectoryListing>),
  LinkDest(LinkDest),
  ProcessResult(Box<ProcessResult>),
  Snapshot(Arc<store::Snapshot>),
  Value(Value),
}

impl NodeOutput {
  pub fn digests(&self) -> Vec<hashing::Digest> {
    match self {
      NodeOutput::Digest(d) => vec![*d],
      NodeOutput::Snapshot(s) => vec![s.digest],
      NodeOutput::ProcessResult(p) => {
        vec![p.0.stdout_digest, p.0.stderr_digest, p.0.output_directory]
      }
      NodeOutput::DirectoryListing(_) | NodeOutput::LinkDest(_) | NodeOutput::Value(_) => vec![],
    }
  }
}

impl TryFrom<NodeOutput> for (Value, Option<log::Level>) {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Value(v) => Ok((v, None)),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for Value {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Value(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for Arc<store::Snapshot> {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Snapshot(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for hashing::Digest {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Digest(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for ProcessResult {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::ProcessResult(v) => Ok(*v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for LinkDest {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::LinkDest(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for Arc<DirectoryListing> {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::DirectoryListing(v) => Ok(v),
      _ => Err(()),
    }
  }
}
