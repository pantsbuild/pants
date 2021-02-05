// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashMap};
use std::convert::{TryFrom, TryInto};
use std::fmt::Display;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use std::{self, fmt};

use async_trait::async_trait;
use futures::future::{self, FutureExt, TryFutureExt};
use futures::stream::StreamExt;
use url::Url;

use crate::context::{Context, Core};
use crate::core::{display_sorted_in_parens, throw, Failure, Key, Params, TypeId, Value};
use crate::externs;
use crate::externs::engine_aware::{self, EngineAwareInformation};
use crate::selectors;
use crate::tasks::{self, Rule};
use crate::Types;
use bytes::buf::BufMutExt;
use cpython::{PyObject, Python, PythonObject};
use fs::{
  self, Dir, DirectoryListing, File, FileContent, GlobExpansionConjunction, GlobMatching, Link,
  PathGlobs, PathStat, PreparedPathGlobs, RelativePath, StrictGlobMatching, VFS,
};
use process_execution::{
  self, CacheDest, CacheName, MultiPlatformProcess, Platform, Process, ProcessCacheScope,
};

use bytes::Bytes;
use graph::{Entry, Node, NodeError, NodeVisualizer};
use hashing::Digest;
use reqwest::Error;
use std::pin::Pin;
use store::{self, StoreFileByDigest};
use workunit_store::{
  with_workunit, ArtifactOutput, Level, UserMetadataItem, UserMetadataPyValue, WorkunitMetadata,
};

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
  fn store_by_digest(
    &self,
    file: File,
  ) -> future::BoxFuture<'static, Result<hashing::Digest, Failure>> {
    let context = self.clone();
    async move { context.get(DigestFile(file)).await }.boxed()
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
            .map(|output| output.value),
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

pub fn lift_directory_digest(digest: &PyObject) -> Result<hashing::Digest, String> {
  externs::fs::from_py_digest(digest).map_err(|e| format!("{:?}", e))
}

pub fn lift_file_digest(types: &Types, digest: &PyObject) -> Result<hashing::Digest, String> {
  if types.file_digest != externs::get_type_for(&digest) {
    return Err(format!("{} is not of type {}.", digest, types.file_digest));
  }
  let fingerprint = externs::getattr_as_string(&digest, "fingerprint");
  let digest_length: usize = externs::getattr(&digest, "serialized_bytes_length").unwrap();
  Ok(hashing::Digest::new(
    hashing::Fingerprint::from_hex_string(&fingerprint)?,
    digest_length,
  ))
}

/// A Node that represents a set of processes to execute on specific platforms.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct MultiPlatformExecuteProcess {
  cache_scope: ProcessCacheScope,
  process: MultiPlatformProcess,
}

impl MultiPlatformExecuteProcess {
  fn lift_process(value: &Value, platform_constraint: Option<Platform>) -> Result<Process, String> {
    let env = externs::getattr_from_frozendict(&value, "env");

    let working_directory = {
      let val = externs::getattr_as_string(&value, "working_directory");
      if val.is_empty() {
        None
      } else {
        Some(RelativePath::new(val.as_str())?)
      }
    };

    let py_digest: Value = externs::getattr(&value, "input_digest").unwrap();
    let digest =
      lift_directory_digest(&py_digest).map_err(|err| format!("Error parsing digest {}", err))?;

    let output_files = externs::getattr::<Vec<String>>(&value, "output_files")
      .unwrap()
      .into_iter()
      .map(RelativePath::new)
      .collect::<Result<_, _>>()?;

    let output_directories = externs::getattr::<Vec<String>>(&value, "output_directories")
      .unwrap()
      .into_iter()
      .map(RelativePath::new)
      .collect::<Result<_, _>>()?;

    let timeout_in_seconds: f64 = externs::getattr(&value, "timeout_seconds").unwrap();

    let timeout = if timeout_in_seconds < 0.0 {
      None
    } else {
      Some(Duration::from_millis((timeout_in_seconds * 1000.0) as u64))
    };

    let description = externs::getattr_as_string(&value, "description");
    let py_level: PyObject = externs::getattr(&value, "level").unwrap();
    let level = externs::val_to_log_level(&py_level)?;

    let append_only_caches = externs::getattr_from_frozendict(&value, "append_only_caches")
      .into_iter()
      .map(|(name, dest)| Ok((CacheName::new(name)?, CacheDest::new(dest)?)))
      .collect::<Result<_, String>>()?;

    let jdk_home = {
      let val = externs::getattr_as_string(&value, "jdk_home");
      if val.is_empty() {
        None
      } else {
        Some(PathBuf::from(val))
      }
    };

    let is_nailgunnable: bool = externs::getattr(&value, "is_nailgunnable").unwrap();

    let execution_slot_variable = {
      let s = externs::getattr_as_string(&value, "execution_slot_variable");
      if s.is_empty() {
        None
      } else {
        Some(s)
      }
    };

    let cache_scope =
      externs::getattr_as_string(&externs::getattr(&value, "cache_scope").unwrap(), "name")
        .try_into()?;

    Ok(process_execution::Process {
      argv: externs::getattr(&value, "argv").unwrap(),
      env,
      working_directory,
      input_files: digest,
      output_files,
      output_directories,
      timeout,
      description,
      level,
      append_only_caches,
      jdk_home,
      platform_constraint,
      is_nailgunnable,
      execution_slot_variable,
      cache_scope,
    })
  }

  pub fn lift(value: &Value) -> Result<MultiPlatformExecuteProcess, String> {
    let raw_constraints = externs::getattr::<Vec<Option<String>>>(&value, "platform_constraints")?;
    let constraints = raw_constraints
      .into_iter()
      .map(|maybe_plat| match maybe_plat {
        Some(plat) => Platform::try_from(plat).map(Some),
        None => Ok(None),
      })
      .collect::<Result<Vec<_>, _>>()?;
    let processes = externs::getattr::<Vec<Value>>(&value, "processes")?;
    if constraints.len() != processes.len() {
      return Err(format!(
        "Sizes of constraint keys and processes do not match: {} vs. {}",
        constraints.len(),
        processes.len()
      ));
    }

    let mut request_by_constraint: BTreeMap<Option<Platform>, Process> = BTreeMap::new();
    for (constraint, execute_process) in constraints.iter().zip(processes.iter()) {
      let underlying_req = MultiPlatformExecuteProcess::lift_process(execute_process, *constraint)?;
      request_by_constraint.insert(*constraint, underlying_req.clone());
    }

    let cache_scope = request_by_constraint
      .values()
      .next()
      .map(|p| p.cache_scope)
      .unwrap();
    Ok(MultiPlatformExecuteProcess {
      cache_scope,
      process: MultiPlatformProcess(request_by_constraint),
    })
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
    let request = self.process;

    if context
      .core
      .command_runner
      .extract_compatible_request(&request)
      .is_some()
    {
      let command_runner = &context.core.command_runner;

      let execution_context = process_execution::Context::new(
        context.session.workunit_store(),
        context.session.build_id().to_string(),
      );

      let res = command_runner
        .run(request, execution_context)
        .await
        .map_err(|e| throw(&e))?;

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
/// A node that captures Vec<PathStat> for resolved files/dirs from PathGlobs.
///
/// This is similar to the Snapshot node, but avoids digesting the files and writing to LMDB store
/// as a performance optimization.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Paths {
  path_globs: PathGlobs,
}

impl Paths {
  pub fn from_path_globs(path_globs: PathGlobs) -> Paths {
    Paths { path_globs }
  }
  async fn create(context: Context, path_globs: PreparedPathGlobs) -> NodeResult<Vec<PathStat>> {
    context
      .expand_globs(path_globs)
      .map_err(|e| throw(&format!("{}", e)))
      .await
  }

  pub fn store_paths(core: &Arc<Core>, item: &[PathStat]) -> Result<Value, String> {
    let mut files = Vec::new();
    let mut dirs = Vec::new();
    for ps in item.iter() {
      match ps {
        &PathStat::File { ref path, .. } => {
          files.push(Snapshot::store_path(path)?);
        }
        &PathStat::Dir { ref path, .. } => {
          dirs.push(Snapshot::store_path(path)?);
        }
      }
    }
    Ok(externs::unsafe_call(
      core.types.paths,
      &[externs::store_tuple(files), externs::store_tuple(dirs)],
    ))
  }
}

#[async_trait]
impl WrappedNode for Paths {
  type Item = Arc<Vec<PathStat>>;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Arc<Vec<PathStat>>> {
    let path_globs = self.path_globs.parse().map_err(|e| throw(&e))?;
    let path_stats = Self::create(context, path_globs).await?;
    Ok(Arc::new(path_stats))
  }
}

impl From<Paths> for NodeKey {
  fn from(n: Paths) -> Self {
    NodeKey::Paths(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SessionValues;

#[async_trait]
impl WrappedNode for SessionValues {
  type Item = Value;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Value> {
    Ok(context.session.session_values())
  }
}

impl From<SessionValues> for NodeKey {
  fn from(n: SessionValues) -> Self {
    NodeKey::SessionValues(n)
  }
}

///
/// A Node that captures an store::Snapshot for a PathGlobs subject.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Snapshot {
  path_globs: PathGlobs,
}

impl Snapshot {
  pub fn from_path_globs(path_globs: PathGlobs) -> Snapshot {
    Snapshot { path_globs }
  }

  async fn create(context: Context, path_globs: PreparedPathGlobs) -> NodeResult<store::Snapshot> {
    // We rely on Context::expand_globs tracking dependencies for scandirs,
    // and store::Snapshot::from_path_stats tracking dependencies for file digests.
    let path_stats = context
      .expand_globs(path_globs)
      .map_err(|e| throw(&format!("{}", e)))
      .await?;
    store::Snapshot::from_path_stats(context.core.store(), context.clone(), path_stats)
      .map_err(|e| throw(&format!("Snapshot failed: {}", e)))
      .await
  }

  pub fn lift_path_globs(item: &Value) -> Result<PathGlobs, String> {
    let globs: Vec<String> = externs::getattr(item, "globs").unwrap();

    let description_of_origin_field = externs::getattr_as_string(item, "description_of_origin");
    let description_of_origin = if description_of_origin_field.is_empty() {
      None
    } else {
      Some(description_of_origin_field)
    };

    let glob_match_error_behavior: PyObject =
      externs::getattr(item, "glob_match_error_behavior").unwrap();
    let failure_behavior = externs::getattr_as_string(&glob_match_error_behavior, "value");
    let strict_glob_matching =
      StrictGlobMatching::create(failure_behavior.as_str(), description_of_origin)?;

    let conjunction_obj: PyObject = externs::getattr(item, "conjunction").unwrap();
    let conjunction_string = externs::getattr_as_string(&conjunction_obj, "value");
    let conjunction = GlobExpansionConjunction::create(&conjunction_string)?;
    Ok(PathGlobs::new(globs, strict_glob_matching, conjunction))
  }

  pub fn lift_prepared_path_globs(item: &Value) -> Result<PreparedPathGlobs, String> {
    let path_globs = Snapshot::lift_path_globs(item)?;
    path_globs
      .parse()
      .map_err(|e| format!("Failed to parse PathGlobs for globs({:?}): {}", item, e))
  }

  pub fn store_directory_digest(item: &hashing::Digest) -> Result<Value, String> {
    externs::fs::to_py_digest(*item)
      .map(|d| d.into_object().into())
      .map_err(|e| format!("{:?}", e))
  }

  pub fn store_file_digest(core: &Arc<Core>, item: &hashing::Digest) -> Value {
    externs::unsafe_call(
      core.types.file_digest,
      &[
        externs::store_utf8(&item.hash.to_hex()),
        externs::store_i64(item.size_bytes as i64),
      ],
    )
  }

  pub fn store_snapshot(item: store::Snapshot) -> Result<Value, String> {
    externs::fs::to_py_snapshot(item)
      .map(|d| d.into_object().into())
      .map_err(|e| format!("{:?}", e))
  }

  fn store_path(item: &Path) -> Result<Value, String> {
    if let Some(p) = item.as_os_str().to_str() {
      Ok(externs::store_utf8(p))
    } else {
      Err(format!("Could not decode path `{:?}` as UTF8.", item))
    }
  }

  fn store_file_content(types: &crate::types::Types, item: &FileContent) -> Result<Value, String> {
    Ok(externs::unsafe_call(
      types.file_content,
      &[
        Self::store_path(&item.path)?,
        externs::store_bytes(&item.content),
        externs::store_bool(item.is_executable),
      ],
    ))
  }

  pub fn store_digest_contents(context: &Context, item: &[FileContent]) -> Result<Value, String> {
    let entries = item
      .iter()
      .map(|e| Self::store_file_content(&context.core.types, e))
      .collect::<Result<Vec<_>, _>>()?;
    Ok(externs::unsafe_call(
      context.core.types.digest_contents,
      &[externs::store_tuple(entries)],
    ))
  }
}

#[async_trait]
impl WrappedNode for Snapshot {
  type Item = Digest;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Digest> {
    let path_globs = self.path_globs.parse().map_err(|e| throw(&e))?;
    let snapshot = Self::create(context, path_globs).await?;
    Ok(snapshot.digest)
  }
}

impl From<Snapshot> for NodeKey {
  fn from(n: Snapshot) -> Self {
    NodeKey::Snapshot(n)
  }
}

#[async_trait]
trait StreamingDownload: Send {
  async fn next(&mut self) -> Option<Result<Bytes, String>>;
}

struct NetDownload {
  stream: futures_core::stream::BoxStream<'static, Result<Bytes, Error>>,
}

impl NetDownload {
  async fn start(core: &Arc<Core>, url: Url, file_name: String) -> Result<NetDownload, String> {
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
    let byte_stream = Pin::new(Box::new(response.bytes_stream()));
    Ok(NetDownload {
      stream: byte_stream,
    })
  }
}

#[async_trait]
impl StreamingDownload for NetDownload {
  async fn next(&mut self) -> Option<Result<Bytes, String>> {
    self
      .stream
      .next()
      .await
      .map(|result| result.map_err(|err| err.to_string()))
  }
}

struct FileDownload {
  stream: tokio::io::ReaderStream<tokio::fs::File>,
}

impl FileDownload {
  async fn start(path: &str, file_name: String) -> Result<FileDownload, String> {
    let file = tokio::fs::File::open(path).await.map_err(|e| {
      format!(
        "Error ({}) opening file at {} for download to {}",
        e, path, file_name
      )
    })?;
    let stream = tokio::io::reader_stream(file);
    Ok(FileDownload { stream })
  }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct DownloadedFile(pub Key);

#[async_trait]
impl StreamingDownload for FileDownload {
  async fn next(&mut self) -> Option<Result<Bytes, String>> {
    self
      .stream
      .next()
      .await
      .map(|result| result.map_err(|err| err.to_string()))
  }
}

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
    let path = RelativePath::new(&file_name).map_err(|e| {
      format!(
        "The file name derived from {} was {} which is not relative: {:?}",
        &url, &file_name, e
      )
    })?;
    let maybe_bytes = core.store().load_file_bytes_with(digest, |_| ()).await?;
    if maybe_bytes.is_none() {
      DownloadedFile::download(core.clone(), url, file_name, digest).await?;
    }
    core.store().snapshot_of_one_file(path, digest, true).await
  }

  async fn start_download(
    core: &Arc<Core>,
    url: Url,
    file_name: String,
  ) -> Result<Box<dyn StreamingDownload>, String> {
    if url.scheme() == "file" {
      return Ok(Box::new(FileDownload::start(url.path(), file_name).await?));
    }
    Ok(Box::new(NetDownload::start(&core, url, file_name).await?))
  }

  async fn download(
    core: Arc<Core>,
    url: Url,
    file_name: String,
    expected_digest: hashing::Digest,
  ) -> Result<(), String> {
    let mut response_stream = DownloadedFile::start_download(&core, url, file_name).await?;

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
        writer: bytes::BytesMut::with_capacity(expected_digest.size_bytes).writer(),
        written: 0,
        size_limit: expected_digest.size_bytes,
      });

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
  type Item = Digest;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<Digest> {
    let value = externs::val_for(&self.0);
    let url_str = externs::getattr_as_string(&value, "url");

    let url = Url::parse(&url_str)
      .map_err(|err| throw(&format!("Error parsing URL {}: {}", url_str, err)))?;

    let py_digest: Value = externs::getattr(&value, "expected_digest").unwrap();
    let expected_digest =
      lift_file_digest(&context.core.types, &py_digest).map_err(|s| throw(&s))?;

    let snapshot = self
      .load_or_download(context.core, url, expected_digest)
      .await
      .map_err(|err| throw(&err))?;
    Ok(snapshot.digest)
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
          output: get.output,
          input: *get.input.type_id(),
        });
        let entry_res = context
          .core
          .rule_graph
          .edges_for_inner(&entry)
          .ok_or_else(|| throw(&format!("No edges for task {:?} exist!", entry)))
          .and_then(|edges| {
            edges.entry_for(&dependency_key).cloned().ok_or_else(|| {
              if externs::is_union(get.input_type) {
                throw(&format!(
                  "Invalid Get. Because the second argument to `Get({}, {}, {:?})` is annotated \
                    with `@union`, the third argument should be a member of that union. Did you \
                    intend to register `UnionRule({}, {})`? If not, you may be using the wrong \
                    type ({}) for the third argument.",
                  get.output,
                  get.input_type,
                  get.input,
                  get.input_type,
                  get.input.type_id(),
                  get.input.type_id(),
                ))
              } else {
                // NB: The Python constructor for `Get()` will have already errored if
                // `type(input) != input_type`.
                throw(&format!(
                  "Could not find a rule to satisfy Get({}, {}, {}).",
                  get.output, get.input_type, get.input
                ))
              }
            })
          });
        // The subject of the get is a new parameter that replaces an existing param of the same
        // type.
        params.put(get.input);
        async move {
          let entry = entry_res?;
          Select::new(params, get.output, entry)
            .run_wrapped_node(context.clone())
            .await
        }
      })
      .collect::<Vec<_>>();
    future::try_join_all(get_futures).await
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
      "Task {{ func: {}, params: {}, product: {}, cacheable: {} }}",
      self.task.func, self.params, self.product, self.task.cacheable,
    )
  }
}

pub struct PythonRuleOutput {
  value: Value,
  new_level: Option<log::Level>,
  message: Option<String>,
  new_artifacts: Vec<(String, ArtifactOutput)>,
  new_metadata: Vec<(String, Value)>,
}

#[async_trait]
impl WrappedNode for Task {
  type Item = PythonRuleOutput;

  async fn run_wrapped_node(self, context: Context) -> NodeResult<PythonRuleOutput> {
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

    let result_val =
      externs::call_function(&externs::val_for(&func.0), &deps).map_err(Failure::from_py_err)?;
    let mut result_val: Value = result_val.into();
    let mut result_type = externs::get_type_for(&result_val);
    if result_type == context.core.types.coroutine {
      result_val = Self::generate(context.clone(), params, entry, result_val).await?;
      result_type = externs::get_type_for(&result_val);
    }

    if result_type == product {
      let (new_level, message, new_artifacts, new_metadata) = if can_modify_workunit {
        (
          engine_aware::EngineAwareLevel::retrieve(&context.core.types, &result_val),
          engine_aware::Message::retrieve(&context.core.types, &result_val),
          engine_aware::Artifacts::retrieve(&context.core.types, &result_val)
            .unwrap_or_else(Vec::new),
          engine_aware::Metadata::retrieve(&context.core.types, &result_val)
            .unwrap_or_else(Vec::new),
        )
      } else {
        (None, None, Vec::new(), Vec::new())
      };
      Ok(PythonRuleOutput {
        value: result_val,
        new_level,
        message,
        new_artifacts,
        new_metadata,
      })
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
  Paths(Paths),
  SessionValues(SessionValues),
  Task(Box<Task>),
}

impl NodeKey {
  fn product_str(&self) -> String {
    match self {
      &NodeKey::MultiPlatformExecuteProcess(..) => "ProcessResult".to_string(),
      &NodeKey::DownloadedFile(..) => "DownloadedFile".to_string(),
      &NodeKey::Select(ref s) => format!("{}", s.product),
      &NodeKey::SessionValues(_) => "SessionValues".to_string(),
      &NodeKey::Task(ref s) => format!("{}", s.product),
      &NodeKey::Snapshot(..) => "Snapshot".to_string(),
      &NodeKey::Paths(..) => "Paths".to_string(),
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
      | &NodeKey::SessionValues { .. }
      | &NodeKey::Snapshot { .. }
      | &NodeKey::Paths { .. }
      | &NodeKey::Task { .. }
      | &NodeKey::DownloadedFile { .. } => None,
    }
  }

  fn workunit_level(&self) -> Level {
    match self {
      NodeKey::Task(ref task) => task.task.display_info.level,
      NodeKey::DownloadedFile(..) => Level::Debug,
      _ => Level::Trace,
    }
  }

  ///
  /// Provides the `name` field in workunits associated with this node. These names
  /// should be friendly to machine-parsing (i.e. "my_node" rather than "My awesome node!").
  ///
  fn workunit_name(&self) -> String {
    match self {
      NodeKey::Task(ref task) => task.task.display_info.name.clone(),
      NodeKey::MultiPlatformExecuteProcess(mp_epr) => mp_epr.process.workunit_name(),
      NodeKey::Snapshot(..) => "snapshot".to_string(),
      NodeKey::Paths(..) => "paths".to_string(),
      NodeKey::DigestFile(..) => "digest_file".to_string(),
      NodeKey::DownloadedFile(..) => "downloaded_file".to_string(),
      NodeKey::ReadLink(..) => "read_link".to_string(),
      NodeKey::Scandir(..) => "scandir".to_string(),
      NodeKey::Select(..) => "select".to_string(),
      NodeKey::SessionValues(..) => "session_values".to_string(),
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
      NodeKey::Snapshot(ref s) => Some(format!("Snapshotting: {}", s.path_globs)),
      NodeKey::Paths(ref s) => Some(format!("Finding files: {}", s.path_globs)),
      NodeKey::MultiPlatformExecuteProcess(mp_epr) => Some(mp_epr.process.user_facing_name()),
      NodeKey::DigestFile(DigestFile(File { path, .. })) => {
        Some(format!("Fingerprinting: {}", path.display()))
      }
      NodeKey::DownloadedFile(ref d) => Some(format!("Downloading: {}", d.0)),
      NodeKey::ReadLink(ReadLink(Link(path))) => Some(format!("Reading link: {}", path.display())),
      NodeKey::Scandir(Scandir(Dir(path))) => {
        Some(format!("Reading directory: {}", path.display()))
      }
      NodeKey::Select(..) => None,
      NodeKey::SessionValues(..) => None,
    }
  }
}

#[async_trait]
impl Node for NodeKey {
  type Context = Context;

  type Item = NodeOutput;
  type Error = Failure;

  async fn run(self, context: Context) -> Result<NodeOutput, Failure> {
    let workunit_state = workunit_store::expect_workunit_state();

    let user_facing_name = self.user_facing_name();
    let workunit_name = self.workunit_name();
    let failure_name = match &self {
      NodeKey::Task(ref task) => {
        let name = workunit_name.clone();
        let engine_aware_param_ty =
          externs::type_for_type_id(context.core.types.engine_aware_parameter);
        let displayable_param_names: Vec<_> = task
          .params
          .keys()
          .filter_map(|key| {
            let value = externs::val_for(key);

            let gil = Python::acquire_gil();
            let py = gil.python();
            let python_type = value.get_type(py);
            if python_type.is_subtype_of(py, &engine_aware_param_ty) {
              engine_aware::DebugHint::retrieve(&context.core.types, &value)
            } else {
              None
            }
          })
          .collect();
        if displayable_param_names.is_empty() {
          name
        } else if displayable_param_names.len() == 1 {
          format!(
            "{} ({})",
            name,
            display_sorted_in_parens(displayable_param_names.iter())
          )
        } else {
          format!(
            "{} {}",
            name,
            display_sorted_in_parens(displayable_param_names.iter())
          )
        }
      }
      _ => workunit_name.clone(),
    };

    let metadata = WorkunitMetadata {
      desc: user_facing_name,
      message: None,
      level: self.workunit_level(),
      blocked: false,
      stdout: None,
      stderr: None,
      artifacts: Vec::new(),
      user_metadata: Vec::new(),
    };
    let metadata2 = metadata.clone();

    let result_future = async move {
      let metadata = metadata2;
      // To avoid races, we must ensure that we have installed a watch for the subject before
      // executing the node logic. But in case of failure, we wait to see if the Node itself
      // fails, and prefer that error message if so (because we have little control over the
      // error messages of the watch API).
      let maybe_watch = if let Some(path) = self.fs_subject() {
        let abs_path = context.core.build_root.join(path);
        context
          .core
          .watcher
          .watch(abs_path)
          .map_err(|e| Context::mk_error(&e))
          .await
      } else {
        Ok(())
      };

      let mut level = metadata.level;
      let mut message = None;
      let mut artifacts = Vec::new();
      let mut user_metadata = Vec::new();

      let context2 = context.clone();
      let mut result = match self {
        NodeKey::DigestFile(n) => n.run_wrapped_node(context).map_ok(NodeOutput::Digest).await,
        NodeKey::DownloadedFile(n) => n.run_wrapped_node(context).map_ok(NodeOutput::Digest).await,
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
        NodeKey::Snapshot(n) => n.run_wrapped_node(context).map_ok(NodeOutput::Digest).await,
        NodeKey::Paths(n) => n.run_wrapped_node(context).map_ok(NodeOutput::Paths).await,
        NodeKey::SessionValues(n) => n.run_wrapped_node(context).map_ok(NodeOutput::Value).await,
        NodeKey::Task(n) => {
          n.run_wrapped_node(context)
            .map_ok(|python_rule_output| {
              if let Some(new_level) = python_rule_output.new_level {
                level = new_level;
              }
              message = python_rule_output.message;
              artifacts = python_rule_output.new_artifacts;
              user_metadata = python_rule_output.new_metadata;
              NodeOutput::Value(python_rule_output.value)
            })
            .await
        }
      };

      result = result.map_err(|failure| failure.with_pushed_frame(&failure_name));

      // If both the Node and the watch failed, prefer the Node's error message.
      match (&result, maybe_watch) {
        (Ok(_), Ok(_)) => {}
        (Err(_), _) => {}
        (Ok(_), Err(e)) => {
          result = Err(e);
        }
      }

      let session = context2.session;
      let final_metadata = WorkunitMetadata {
        level,
        message,
        artifacts,
        user_metadata: user_metadata
          .into_iter()
          .map(|(key, val)| {
            let py_value_handle = UserMetadataPyValue::new();
            let umi = UserMetadataItem::PyValue(py_value_handle.clone());
            session.with_metadata_map(|map| {
              let val = val.clone();
              map.insert(py_value_handle.clone(), val);
            });
            (key, umi)
          })
          .collect(),
        ..metadata
      };
      (result, final_metadata)
    };

    with_workunit(
      workunit_state.store,
      workunit_name,
      metadata,
      result_future,
      |result, _| result.1.clone(),
    )
    .await
    .0
  }

  fn cacheable(&self) -> bool {
    match self {
      &NodeKey::Task(ref s) => s.task.cacheable,
      &NodeKey::SessionValues(_) => false,
      _ => true,
    }
  }

  fn cacheable_item(&self, output: &NodeOutput) -> bool {
    match self {
      NodeKey::MultiPlatformExecuteProcess(ref mp) => match output {
        NodeOutput::ProcessResult(ref process_result) => match mp.cache_scope {
          ProcessCacheScope::Always | ProcessCacheScope::PerRestart => true,
          ProcessCacheScope::Successful => process_result.0.exit_code == 0,
          ProcessCacheScope::Never => false,
        },
        _ => true,
      },
      _ => true,
    }
  }
}

impl Display for NodeKey {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    match self {
      &NodeKey::DigestFile(ref s) => write!(f, "DigestFile({})", s.0.path.display()),
      &NodeKey::DownloadedFile(ref s) => write!(f, "DownloadedFile({})", s.0),
      &NodeKey::MultiPlatformExecuteProcess(ref s) => {
        write!(f, "Process({})", s.process.user_facing_name())
      }
      &NodeKey::ReadLink(ref s) => write!(f, "ReadLink({})", (s.0).0.display()),
      &NodeKey::Scandir(ref s) => write!(f, "Scandir({})", (s.0).0.display()),
      &NodeKey::Select(ref s) => write!(f, "{}", s.product),
      &NodeKey::Task(ref task) => {
        // TODO(#7907) we probably want to include some kind of representation of
        // the Params of an @rule when we stringify the @rule. But we need to make
        // sure we don't naively dump the string representation of a Key, which
        // could get gigantic.
        write!(f, "@rule({})", task.task.display_info.name)
      }
      &NodeKey::Snapshot(ref s) => write!(f, "Snapshot({})", s.path_globs),
      &NodeKey::SessionValues(_) => write!(f, "SessionValues"),
      &NodeKey::Paths(ref s) => write!(f, "Paths({})", s.path_globs),
    }
  }
}

impl NodeError for Failure {
  fn invalidated() -> Failure {
    Failure::Invalidated
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
  // Allow clippy::rc_buffer due to non-trivial issues that would arise in using the
  // suggested Arc<[PathStat]> type. See https://github.com/rust-lang/rust-clippy/issues/6170
  #[allow(clippy::rc_buffer)]
  Paths(Arc<Vec<PathStat>>),
  Value(Value),
}

impl NodeOutput {
  pub fn digests(&self) -> Vec<hashing::Digest> {
    match self {
      NodeOutput::Digest(d) => vec![*d],
      NodeOutput::ProcessResult(p) => {
        vec![p.0.stdout_digest, p.0.stderr_digest, p.0.output_directory]
      }
      NodeOutput::DirectoryListing(_)
      | NodeOutput::LinkDest(_)
      | NodeOutput::Paths(_)
      | NodeOutput::Value(_) => vec![],
    }
  }
}

impl TryFrom<NodeOutput> for PythonRuleOutput {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Value(v) => Ok(PythonRuleOutput {
        value: v,
        new_level: None,
        message: None,
        new_artifacts: Vec::new(),
        new_metadata: Vec::new(),
      }),
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

impl TryFrom<NodeOutput> for hashing::Digest {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Digest(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for Arc<Vec<PathStat>> {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Paths(v) => Ok(v),
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
