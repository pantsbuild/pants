// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashMap};
use std::convert::{TryFrom, TryInto};
use std::fmt;
use std::fmt::Display;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use bytes::Bytes;
use futures::future::{self, BoxFuture, FutureExt, TryFutureExt};
use grpc_util::prost::MessageExt;
use protos::gen::pants::cache::{CacheKey, CacheKeyType, ObservedUrl};
use pyo3::prelude::Python;
use url::Url;

use crate::context::{Context, Core};
use crate::downloads;
use crate::externs;
use crate::python::{display_sorted_in_parens, throw, Failure, Key, Params, TypeId, Value};
use crate::selectors;
use crate::tasks::{self, Rule};
use crate::Types;
use cpython::PythonObject;
use fs::{
  self, DigestEntry, Dir, DirectoryListing, File, FileContent, FileEntry, GlobExpansionConjunction,
  GlobMatching, Link, PathGlobs, PathStat, PreparedPathGlobs, RelativePath, StrictGlobMatching,
  Vfs,
};
use process_execution::{
  self, CacheDest, CacheName, MultiPlatformProcess, Platform, Process, ProcessCacheScope,
  ProcessResultSource,
};

use crate::externs::engine_aware::{EngineAwareParameter, EngineAwareReturnType};
use graph::{Entry, Node, NodeError, NodeVisualizer};
use hashing::{Digest, Fingerprint};
use store::{self, StoreFileByDigest};
use workunit_store::{
  in_workunit, Level, Metric, ObservationMetric, RunningWorkunit, UserMetadataItem,
  WorkunitMetadata,
};

tokio::task_local! {
    static TASK_SIDE_EFFECTED: Arc<AtomicBool>;
}

pub fn task_side_effected() -> Result<(), String> {
  TASK_SIDE_EFFECTED
    .try_with(|task_side_effected| {
      task_side_effected.store(true, Ordering::SeqCst);
    })
    .map_err(|_| {
      "Side-effects are not allowed in this context: SideEffecting types must be \
            acquired via parameters to `@rule`s."
        .to_owned()
    })
}

pub async fn maybe_side_effecting<T, F: future::Future<Output = T>>(
  is_side_effecting: bool,
  side_effected: &Arc<AtomicBool>,
  f: F,
) -> T {
  if is_side_effecting {
    TASK_SIDE_EFFECTED.scope(side_effected.clone(), f).await
  } else {
    f.await
  }
}

pub type NodeResult<T> = Result<T, Failure>;

#[async_trait]
impl Vfs<Failure> for Context {
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

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Self::Item>;
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

  fn select_product(
    &self,
    context: &Context,
    product: TypeId,
    caller_description: &str,
  ) -> BoxFuture<NodeResult<Value>> {
    let edges = context
      .core
      .rule_graph
      .edges_for_inner(&self.entry)
      .ok_or_else(|| {
        throw(&format!(
          "Tried to select product {} for {} but found no edges",
          product, caller_description
        ))
      });
    let params = self.params.clone();
    let context = context.clone();
    async move {
      let edges = edges?;
      Select::new_from_edges(params, product, &edges)
        .run(context)
        .await
    }
    .boxed()
  }

  async fn run(self, context: Context) -> NodeResult<Value> {
    match &self.entry {
      &rule_graph::Entry::WithDeps(rule_graph::EntryWithDeps::Inner(ref inner)) => {
        match inner.rule() {
          &tasks::Rule::Task(ref task) => {
            context
              .get(Task {
                params: self.params.clone(),
                product: self.product,
                task: task.clone(),
                entry: Arc::new(self.entry.clone()),
                side_effected: Arc::new(AtomicBool::new(false)),
              })
              .await
          }
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
          Ok(key.to_value())
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

///
/// NB: This is a Node so that it can be used as a root in the graph, but it should otherwise
/// never be requested as a Node using context.get. Select is a thin proxy to other Node types
/// (which it requests using context.get), and memoizing it would be redundant.
///
/// Instead, use `Select::run` to run the Select logic without memoizing it.
///
#[async_trait]
impl WrappedNode for Select {
  type Item = Value;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Value> {
    self.run(context).await
  }
}

impl From<Select> for NodeKey {
  fn from(n: Select) -> Self {
    NodeKey::Select(Box::new(n))
  }
}

pub fn lift_directory_digest(digest: &cpython::PyObject) -> Result<hashing::Digest, String> {
  externs::fs::from_py_digest(digest).map_err(|e| format!("{:?}", e))
}

pub fn lift_file_digest(
  types: &Types,
  digest: &cpython::PyObject,
) -> Result<hashing::Digest, String> {
  let gil = cpython::Python::acquire_gil();
  let py = gil.python();
  if TypeId::new(&digest.get_type(py)) != types.file_digest {
    return Err(format!("{} is not of type {}.", digest, types.file_digest));
  }
  let fingerprint: String = externs::getattr(digest, "fingerprint").unwrap();
  let digest_length: usize = externs::getattr(digest, "serialized_bytes_length").unwrap();
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
    let gil = cpython::Python::acquire_gil();
    let py = gil.python();
    let env = externs::getattr_from_str_frozendict(value, "env");
    let working_directory =
      match externs::getattr_as_optional_string(py, value, "working_directory") {
        None => None,
        Some(dir) => Some(RelativePath::new(dir)?),
      };

    let py_digest: Value = externs::getattr(value, "input_digest").unwrap();
    let digest = lift_directory_digest(&py_digest)
      .map_err(|err| format!("Error parsing input_digest {}", err))?;

    let output_files = externs::getattr::<Vec<String>>(value, "output_files")
      .unwrap()
      .into_iter()
      .map(RelativePath::new)
      .collect::<Result<_, _>>()?;

    let output_directories = externs::getattr::<Vec<String>>(value, "output_directories")
      .unwrap()
      .into_iter()
      .map(RelativePath::new)
      .collect::<Result<_, _>>()?;

    let timeout_in_seconds: f64 = externs::getattr(value, "timeout_seconds").unwrap();

    let timeout = if timeout_in_seconds < 0.0 {
      None
    } else {
      Some(Duration::from_millis((timeout_in_seconds * 1000.0) as u64))
    };

    let description: String = externs::getattr(value, "description").unwrap();
    let py_level: cpython::PyObject = externs::getattr(value, "level").unwrap();
    let level = externs::val_to_log_level(&py_level)?;

    let append_only_caches = externs::getattr_from_str_frozendict(value, "append_only_caches")
      .into_iter()
      .map(|(name, dest)| Ok((CacheName::new(name)?, CacheDest::new(dest)?)))
      .collect::<Result<_, String>>()?;

    let jdk_home = externs::getattr_as_optional_string(py, value, "jdk_home").map(PathBuf::from);

    let py_use_nailgun: Value = externs::getattr(value, "use_nailgun").unwrap();
    let use_nailgun = lift_directory_digest(&py_use_nailgun)
      .map_err(|err| format!("Error parsing use_nailgun {}", err))?;

    let execution_slot_variable =
      externs::getattr_as_optional_string(py, value, "execution_slot_variable");

    let cache_scope: ProcessCacheScope = {
      let cache_scope_enum: cpython::PyObject = externs::getattr(value, "cache_scope").unwrap();
      externs::getattr::<String>(&cache_scope_enum, "name")
        .unwrap()
        .try_into()?
    };

    Ok(process_execution::Process {
      argv: externs::getattr(value, "argv").unwrap(),
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
      use_nailgun,
      execution_slot_variable,
      cache_scope,
    })
  }

  pub fn lift(value: &Value) -> Result<MultiPlatformExecuteProcess, String> {
    let raw_constraints = externs::getattr::<Vec<Option<String>>>(value, "platform_constraints")?;
    let constraints = raw_constraints
      .into_iter()
      .map(|maybe_plat| match maybe_plat {
        Some(plat) => Platform::try_from(plat).map(Some),
        None => Ok(None),
      })
      .collect::<Result<Vec<_>, _>>()?;
    let processes = externs::getattr::<Vec<Value>>(value, "processes")?;
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

  async fn run_wrapped_node(
    self,
    context: Context,
    workunit: &mut RunningWorkunit,
  ) -> NodeResult<ProcessResult> {
    let request = self.process;

    if let Some(compatible_request) = context
      .core
      .command_runner
      .extract_compatible_request(&request)
    {
      let command_runner = &context.core.command_runner;

      let execution_context = process_execution::Context::new(
        context.session.workunit_store(),
        context.session.build_id().to_string(),
      );

      let res = command_runner
        .run(execution_context, workunit, request)
        .await
        .map_err(|e| throw(&e))?;

      let definition = serde_json::to_string(&compatible_request)
        .map_err(|e| throw(&format!("Failed to serialize process: {}", e)))?;
      workunit.update_metadata(|initial| WorkunitMetadata {
        stdout: Some(res.stdout_digest),
        stderr: Some(res.stderr_digest),
        user_metadata: vec![
          (
            "definition".to_string(),
            UserMetadataItem::ImmediateString(definition),
          ),
          (
            "source".to_string(),
            UserMetadataItem::ImmediateString(format!("{:?}", res.metadata.source)),
          ),
          (
            "exit_code".to_string(),
            UserMetadataItem::ImmediateInt(res.exit_code as i64),
          ),
        ],
        ..initial
      });
      if let Some(total_elapsed) = res.metadata.total_elapsed {
        let total_elapsed = Duration::from(total_elapsed).as_millis() as u64;
        match res.metadata.source {
          ProcessResultSource::RanLocally => {
            workunit.increment_counter(Metric::LocalProcessTotalTimeRunMs, total_elapsed);
            context
              .session
              .workunit_store()
              .record_observation(ObservationMetric::LocalProcessTimeRunMs, total_elapsed);
          }
          ProcessResultSource::RanRemotely => {
            workunit.increment_counter(Metric::RemoteProcessTotalTimeRunMs, total_elapsed);
            context
              .session
              .workunit_store()
              .record_observation(ObservationMetric::RemoteProcessTimeRunMs, total_elapsed);
          }
          _ => {}
        }
      }

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

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<LinkDest> {
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

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<hashing::Digest> {
    let path = context.core.vfs.file_path(&self.0);
    context
      .core
      .store()
      .store_file(true, false, move || std::fs::File::open(&path))
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

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Arc<DirectoryListing>> {
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

fn unmatched_globs_additional_context() -> Option<String> {
  let gil = Python::acquire_gil();
  let url = externs::doc_url(
    gil.python(),
    "troubleshooting#pants-cannot-find-a-file-in-your-project",
  );
  Some(format!(
    "\n\nDo the file(s) exist? If so, check if the file(s) are in your `.gitignore` or the global \
    `pants_ignore` option, which may result in Pants not being able to see the file(s) even though \
    they exist on disk. Refer to {}.",
    url
  ))
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
      .expand_globs(path_globs, unmatched_globs_additional_context())
      .map_err(|e| throw(&format!("{}", e)))
      .await
  }

  pub fn store_paths(py: Python, core: &Arc<Core>, item: &[PathStat]) -> Result<Value, String> {
    let mut files = Vec::new();
    let mut dirs = Vec::new();
    for ps in item.iter() {
      match ps {
        &PathStat::File { ref path, .. } => {
          files.push(Snapshot::store_path(py, path)?);
        }
        &PathStat::Dir { ref path, .. } => {
          dirs.push(Snapshot::store_path(py, path)?);
        }
      }
    }
    Ok(externs::unsafe_call(
      py,
      core.types.paths,
      &[
        externs::store_tuple(py, files),
        externs::store_tuple(py, dirs),
      ],
    ))
  }
}

#[async_trait]
impl WrappedNode for Paths {
  type Item = Arc<Vec<PathStat>>;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Arc<Vec<PathStat>>> {
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

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Value> {
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
      .expand_globs(path_globs, unmatched_globs_additional_context())
      .map_err(|e| throw(&format!("{}", e)))
      .await?;
    store::Snapshot::from_path_stats(context.core.store(), context.clone(), path_stats)
      .map_err(|e| throw(&format!("Snapshot failed: {}", e)))
      .await
  }

  pub fn lift_path_globs(item: &Value) -> Result<PathGlobs, String> {
    let gil = cpython::Python::acquire_gil();
    let py = gil.python();
    let globs: Vec<String> = externs::getattr(item, "globs").unwrap();
    let description_of_origin =
      externs::getattr_as_optional_string(py, item, "description_of_origin");

    let glob_match_error_behavior: cpython::PyObject =
      externs::getattr(item, "glob_match_error_behavior").unwrap();
    let failure_behavior: String = externs::getattr(&glob_match_error_behavior, "value").unwrap();
    let strict_glob_matching =
      StrictGlobMatching::create(failure_behavior.as_str(), description_of_origin)?;

    let conjunction_obj: cpython::PyObject = externs::getattr(item, "conjunction").unwrap();
    let conjunction_string: String = externs::getattr(&conjunction_obj, "value").unwrap();
    let conjunction = GlobExpansionConjunction::create(&conjunction_string)?;
    Ok(PathGlobs::new(globs, strict_glob_matching, conjunction))
  }

  pub fn lift_prepared_path_globs(item: &Value) -> Result<PreparedPathGlobs, String> {
    let path_globs = Snapshot::lift_path_globs(item)?;
    path_globs
      .parse()
      .map_err(|e| format!("Failed to parse PathGlobs for globs({:?}): {}", item, e))
  }

  pub fn store_directory_digest(py: Python, item: &hashing::Digest) -> Result<Value, String> {
    externs::fs::to_py_digest(py, *item)
      .map(|d| d.into_object().into())
      .map_err(|e| format!("{:?}", e))
  }

  pub fn lift_file_digest(item: &cpython::PyObject) -> Result<hashing::Digest, String> {
    let fingerprint: String = externs::getattr(item, "fingerprint").unwrap();
    let serialized_bytes_length: usize = externs::getattr(item, "serialized_bytes_length")?;
    Ok(hashing::Digest::new(
      Fingerprint::from_hex_string(&fingerprint)?,
      serialized_bytes_length,
    ))
  }

  pub fn store_file_digest(
    py: Python,
    types: &crate::types::Types,
    item: &hashing::Digest,
  ) -> Value {
    externs::unsafe_call(
      py,
      types.file_digest,
      &[
        externs::store_utf8(py, &item.hash.to_hex()),
        externs::store_i64(py, item.size_bytes as i64),
      ],
    )
  }

  pub fn store_snapshot(py: Python, item: store::Snapshot) -> Result<Value, String> {
    externs::fs::to_py_snapshot(py, item)
      .map(|d| d.into_object().into())
      .map_err(|e| format!("{:?}", e))
  }

  fn store_path(py: Python, item: &Path) -> Result<Value, String> {
    if let Some(p) = item.as_os_str().to_str() {
      Ok(externs::store_utf8(py, p))
    } else {
      Err(format!("Could not decode path `{:?}` as UTF8.", item))
    }
  }

  fn store_file_content(
    py: Python,
    types: &crate::types::Types,
    item: &FileContent,
  ) -> Result<Value, String> {
    Ok(externs::unsafe_call(
      py,
      types.file_content,
      &[
        Self::store_path(py, &item.path)?,
        externs::store_bytes(py, &item.content),
        externs::store_bool(py, item.is_executable),
      ],
    ))
  }

  fn store_file_entry(
    py: Python,
    types: &crate::types::Types,
    item: &FileEntry,
  ) -> Result<Value, String> {
    Ok(externs::unsafe_call(
      py,
      types.file_entry,
      &[
        Self::store_path(py, &item.path)?,
        Self::store_file_digest(py, types, &item.digest),
        externs::store_bool(py, item.is_executable),
      ],
    ))
  }

  fn store_empty_directory(
    py: Python,
    types: &crate::types::Types,
    path: &Path,
  ) -> Result<Value, String> {
    Ok(externs::unsafe_call(
      py,
      types.directory,
      &[Self::store_path(py, path)?],
    ))
  }

  pub fn store_digest_contents(
    py: Python,
    context: &Context,
    item: &[FileContent],
  ) -> Result<Value, String> {
    let entries = item
      .iter()
      .map(|e| Self::store_file_content(py, &context.core.types, e))
      .collect::<Result<Vec<_>, _>>()?;
    Ok(externs::unsafe_call(
      py,
      context.core.types.digest_contents,
      &[externs::store_tuple(py, entries)],
    ))
  }

  pub fn store_digest_entries(
    py: Python,
    context: &Context,
    item: &[DigestEntry],
  ) -> Result<Value, String> {
    let entries = item
      .iter()
      .map(|digest_entry| match digest_entry {
        DigestEntry::File(file_entry) => {
          Self::store_file_entry(py, &context.core.types, file_entry)
        }
        DigestEntry::EmptyDirectory(path) => {
          Self::store_empty_directory(py, &context.core.types, path)
        }
      })
      .collect::<Result<Vec<_>, _>>()?;
    Ok(externs::unsafe_call(
      py,
      context.core.types.digest_entries,
      &[externs::store_tuple(py, entries)],
    ))
  }
}

#[async_trait]
impl WrappedNode for Snapshot {
  type Item = Digest;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Digest> {
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

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct DownloadedFile(pub Key);

impl DownloadedFile {
  fn url_key(url: &Url, digest: Digest) -> CacheKey {
    let observed_url = ObservedUrl {
      url: url.path().to_owned(),
      observed_digest: Some(digest.into()),
    };
    CacheKey {
      key_type: CacheKeyType::Url.into(),
      digest: Some(Digest::of_bytes(&observed_url.to_bytes()).into()),
    }
  }

  pub async fn load_or_download(
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

    // See if we have observed this URL and Digest before: if so, see whether we already have the
    // Digest fetched. The extra layer of indirection through the PersistentCache is to sanity
    // check that a Digest has ever been observed at the given URL.
    let url_key = Self::url_key(&url, digest);
    let have_observed_url = core.local_cache.load(&url_key).await?.is_some();

    // If we hit the ObservedUrls cache, then we have successfully fetched this Digest from
    // this URL before. If we still have the bytes, then we skip fetching the content again.
    let usable_in_store = have_observed_url
      && core
        .store()
        .load_file_bytes_with(digest, |_| ())
        .await?
        .is_some();

    if !usable_in_store {
      downloads::download(core.clone(), url, file_name, digest).await?;
      // The value was successfully fetched and matched the digest: record in the ObservedUrls
      // cache.
      core.local_cache.store(&url_key, Bytes::from("")).await?;
    }
    core.store().snapshot_of_one_file(path, digest, true).await
  }
}

#[async_trait]
impl WrappedNode for DownloadedFile {
  type Item = Digest;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Digest> {
    let value = self.0.to_value();
    let url_str: String = externs::getattr(&value, "url").unwrap();

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

#[derive(Derivative, Clone)]
#[derivative(Eq, PartialEq, Hash)]
pub struct Task {
  params: Params,
  product: TypeId,
  task: tasks::Task,
  // The Params and the Task struct are sufficient to uniquely identify it.
  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  entry: Arc<rule_graph::Entry<Rule>>,
  // Does not affect the identity of the Task.
  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  side_effected: Arc<AtomicBool>,
}

impl Task {
  async fn gen_get(
    context: &Context,
    workunit: &mut RunningWorkunit,
    params: &Params,
    entry: &Arc<rule_graph::Entry<Rule>>,
    gets: Vec<externs::Get>,
  ) -> NodeResult<Vec<Value>> {
    // While waiting for dependencies, mark the workunit for this Task blocked.
    let _blocking_token = workunit.blocking();
    let get_futures = gets
      .into_iter()
      .map(|get| {
        let context = context.clone();
        let mut params = params.clone();
        let entry = entry.clone();
        async move {
          let dependency_key = selectors::DependencyKey::JustGet(selectors::Get {
            output: get.output,
            input: *get.input.type_id(),
          });
          params.put(get.input);

          let edges = context
            .core
            .rule_graph
            .edges_for_inner(&entry)
            .ok_or_else(|| throw(&format!("No edges for task {:?} exist!", entry)))?;

          // See if there is a Get: otherwise, a union (which is executed as a Query).
          // See #12934 for further cleanup of this API.
          let select = edges
            .entry_for(&dependency_key)
            .cloned()
            .map(|entry| {
              // The subject of the get is a new parameter that replaces an existing param of the same
              // type.
              Select::new(params.clone(), get.output, entry)
            })
            .or_else(|| {
              if get.input_type.is_union() {
                // Is a union.
                let (_, rule_edges) = context
                  .core
                  .rule_graph
                  .find_root(vec![*get.input.type_id()], get.output)
                  .ok()?;
                Some(Select::new_from_edges(params, get.output, &rule_edges))
              } else {
                None
              }
            })
            .ok_or_else(|| {
              if get.input_type.is_union() {
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
                  "Get({}, {}, {}) was not detected in your @rule body at rule compile time. \
                  Was the `Get` constructor called in a separate function, or perhaps \
                  dynamically? If so, it must be inlined into the @rule body.",
                  get.output, get.input_type, get.input
                ))
              }
            })?;
          select.run(context).await
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
    context: &Context,
    workunit: &mut RunningWorkunit,
    params: Params,
    entry: Arc<rule_graph::Entry<Rule>>,
    generator: Value,
  ) -> NodeResult<Value> {
    let mut input = {
      let gil = Python::acquire_gil();
      Value::from(gil.python().None())
    };
    loop {
      let context = context.clone();
      let params = params.clone();
      let entry = entry.clone();
      match externs::generator_send(&generator, &input)? {
        externs::GeneratorResponse::Get(get) => {
          let values = Self::gen_get(&context, workunit, &params, &entry, vec![get]).await?;
          input = values.into_iter().next().unwrap();
        }
        externs::GeneratorResponse::GetMulti(gets) => {
          let values = Self::gen_get(&context, workunit, &params, &entry, gets).await?;
          let gil = Python::acquire_gil();
          input = externs::store_tuple(gil.python(), values);
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

#[async_trait]
impl WrappedNode for Task {
  type Item = Value;

  async fn run_wrapped_node(
    self,
    context: Context,
    workunit: &mut RunningWorkunit,
  ) -> NodeResult<Value> {
    let params = self.params;
    let deps = {
      // While waiting for dependencies, mark ourselves blocking.
      let _blocking_token = workunit.blocking();
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
            Select::new_from_edges(params.clone(), type_id, edges).run(context.clone())
          })
          .collect::<Vec<_>>(),
      )
      .await?
    };

    let func = self.task.func;

    let mut result_val: Value =
      maybe_side_effecting(self.task.side_effecting, &self.side_effected, async move {
        externs::call_function(&func.0.to_value(), &deps).map_err(Failure::from_py_err)
      })
      .await?
      .into();
    let mut result_type = {
      let gil = cpython::Python::acquire_gil();
      let py = gil.python();
      TypeId::new(&result_val.get_type(py))
    };

    if result_type == context.core.types.coroutine {
      result_val = maybe_side_effecting(
        self.task.side_effecting,
        &self.side_effected,
        Self::generate(&context, workunit, params, self.entry, result_val),
      )
      .await?;
      let gil = cpython::Python::acquire_gil();
      let py = gil.python();
      result_type = TypeId::new(&result_val.get_type(py));
    }

    if result_type != self.product {
      return Err(throw(&format!(
        "{:?} returned a result value that did not satisfy its constraints: {:?}",
        func, result_val
      )));
    }

    let engine_aware_return_type = if self.task.engine_aware_return_type {
      let gil = cpython::Python::acquire_gil();
      let py = gil.python();
      EngineAwareReturnType::from_task_result(py, &result_val, &context)
    } else {
      EngineAwareReturnType::default()
    };
    engine_aware_return_type.update_workunit(workunit);

    Ok(result_val)
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
      NodeKey::MultiPlatformExecuteProcess(..) => {
        // NB: The Node for a Process is statically rendered at Debug (rather than at
        // Process.level) because it is very likely to wrap a BoundedCommandRunner which
        // will block the workunit. We don't want to render at the Process's actual level
        // until we're certain that it has begun executing (if at all).
        Level::Debug
      }
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
      NodeKey::MultiPlatformExecuteProcess(..) => "multi_platform_process".to_string(),
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
      NodeKey::MultiPlatformExecuteProcess(mp_epr) => {
        // NB: See Self::workunit_level for more information on why this is prefixed.
        Some(format!("Scheduling: {}", mp_epr.process.user_facing_name()))
      }
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
    let workunit_store_handle = workunit_store::expect_workunit_store_handle();

    let workunit_name = self.workunit_name();
    let user_facing_name = self.user_facing_name();
    let engine_aware_params: Vec<_> = match &self {
      NodeKey::Task(ref task) => {
        let gil = Python::acquire_gil();
        let py = gil.python();
        let engine_aware_param_ty = context.core.types.engine_aware_parameter.as_py_type(py);
        task
          .params
          .keys()
          .filter_map(|key| {
            if key
              .type_id()
              .as_py_type(py)
              .is_subtype_of(py, &engine_aware_param_ty)
            {
              Some(key.to_value())
            } else {
              None
            }
          })
          .collect()
      }
      _ => vec![],
    };
    let user_metadata = {
      let gil = Python::acquire_gil();
      let py = gil.python();
      engine_aware_params
        .iter()
        .flat_map(|val| EngineAwareParameter::metadata(py, &context, val))
        .collect()
    };

    let metadata = WorkunitMetadata {
      desc: user_facing_name,
      level: self.workunit_level(),
      user_metadata,
      ..WorkunitMetadata::default()
    };

    in_workunit!(
      workunit_store_handle.store,
      self.workunit_name(),
      metadata,
      |workunit| async move {
        // To avoid races, we must ensure that we have installed a watch for the subject before
        // executing the node logic. But in case of failure, we wait to see if the Node itself
        // fails, and prefer that error message if so (because we have little control over the
        // error messages of the watch API).
        let maybe_watch = if let Some(path) = self.fs_subject() {
          if let Some(watcher) = &context.core.watcher {
            let abs_path = context.core.build_root.join(path);
            watcher
              .watch(abs_path)
              .map_err(|e| Context::mk_error(&e))
              .await
          } else {
            Ok(())
          }
        } else {
          Ok(())
        };

        let mut result = match self {
          NodeKey::DigestFile(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Digest)
              .await
          }
          NodeKey::DownloadedFile(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Digest)
              .await
          }
          NodeKey::MultiPlatformExecuteProcess(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(|r| NodeOutput::ProcessResult(Box::new(r)))
              .await
          }
          NodeKey::ReadLink(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::LinkDest)
              .await
          }
          NodeKey::Scandir(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::DirectoryListing)
              .await
          }
          NodeKey::Select(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Value)
              .await
          }
          NodeKey::Snapshot(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Digest)
              .await
          }
          NodeKey::Paths(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Paths)
              .await
          }
          NodeKey::SessionValues(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Value)
              .await
          }
          NodeKey::Task(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Value)
              .await
          }
        };

        // If both the Node and the watch failed, prefer the Node's error message.
        match (&result, maybe_watch) {
          (Ok(_), Ok(_)) => {}
          (Err(_), _) => {}
          (Ok(_), Err(e)) => {
            result = Err(e);
          }
        }

        // If the node failed, expand the Failure with a new frame.
        result = result.map_err(|failure| {
          let name = workunit_name;
          let displayable_param_names: Vec<_> = {
            let gil = Python::acquire_gil();
            let py = gil.python();
            engine_aware_params
              .iter()
              .filter_map(|val| EngineAwareParameter::debug_hint(py, val))
              .collect()
          };
          let failure_name = if displayable_param_names.is_empty() {
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
          };

          failure.with_pushed_frame(&failure_name)
        });

        result
      }
    )
    .await
  }

  fn restartable(&self) -> bool {
    // A Task / @rule is only restartable if it has not had a side effect (as determined by the
    // calls to the `task_side_effected` function).
    match self {
      &NodeKey::Task(ref s) => !s.side_effected.load(Ordering::SeqCst),
      _ => true,
    }
  }

  fn cacheable(&self) -> bool {
    match self {
      &NodeKey::Task(ref s) => s.task.cacheable,
      &NodeKey::SessionValues(_) => false,
      _ => true,
    }
  }

  fn cacheable_item(&self, output: &NodeOutput) -> bool {
    match (self, output) {
      (
        NodeKey::MultiPlatformExecuteProcess(ref mp),
        NodeOutput::ProcessResult(ref process_result),
      ) => match mp.cache_scope {
        ProcessCacheScope::Always | ProcessCacheScope::PerRestartAlways => true,
        ProcessCacheScope::Successful | ProcessCacheScope::PerRestartSuccessful => {
          process_result.0.exit_code == 0
        }
        ProcessCacheScope::PerSession => false,
      },
      (NodeKey::Task(ref t), NodeOutput::Value(ref v)) if t.task.engine_aware_return_type => {
        let gil = Python::acquire_gil();
        EngineAwareReturnType::is_cacheable(gil.python(), v).unwrap_or(true)
      }
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
        let params = {
          let gil = Python::acquire_gil();
          let py = gil.python();
          task
            .params
            .keys()
            .filter_map(|k| EngineAwareParameter::debug_hint(py, &k.to_value()))
            .collect::<Vec<_>>()
        };
        write!(
          f,
          "@rule({}({}))",
          task.task.display_info.name,
          params.join(", ")
        )
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
    let gil = Python::acquire_gil();
    let url = externs::doc_url(
      gil.python(),
      "targets#dependencies-and-dependency-inference",
    );
    throw(&format!(
      "The dependency graph contained a cycle:\
      \n\n  \
      {}\
      \n\n\
      If the dependencies in the above path are for your BUILD targets, you may need to use more \
      granular targets or replace BUILD target dependencies with file dependencies. If they are \
      not for your BUILD targets, then please file a Github issue!\
      \n\n\
      See {} for more information.",
      path.join("\n  "),
      url
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
