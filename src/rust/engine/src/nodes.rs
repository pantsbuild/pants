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
use deepsize::DeepSizeOf;
use futures::future::{self, BoxFuture, FutureExt, TryFutureExt};
use grpc_util::prost::MessageExt;
use internment::Intern;
use protos::gen::pants::cache::{CacheKey, CacheKeyType, ObservedUrl};
use pyo3::prelude::{Py, PyAny, Python};
use pyo3::IntoPy;
use url::Url;

use crate::context::{Context, Core};
use crate::downloads;
use crate::externs;
use crate::python::{display_sorted_in_parens, throw, Failure, Key, Params, TypeId, Value};
use crate::selectors;
use crate::tasks::{self, Rule};
use fs::{
  self, DigestEntry, Dir, DirectoryDigest, DirectoryListing, File, FileContent, FileEntry,
  GlobExpansionConjunction, GlobMatching, Link, PathGlobs, PathStat, PreparedPathGlobs,
  RelativePath, StrictGlobMatching, Vfs,
};
use process_execution::{
  self, CacheName, InputDigests, Platform, Process, ProcessCacheScope, ProcessResultSource,
};

use crate::externs::engine_aware::{EngineAwareParameter, EngineAwareReturnType};
use crate::externs::fs::PyFileDigest;
use graph::{Entry, Node, NodeError, NodeVisualizer};
use hashing::Digest;
use store::{self, Store, StoreFileByDigest};
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
    throw(msg.to_owned())
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
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Select {
  pub params: Params,
  pub product: TypeId,
  entry: Intern<rule_graph::Entry<Rule>>,
}

impl Select {
  pub fn new(
    mut params: Params,
    product: TypeId,
    entry: Intern<rule_graph::Entry<Rule>>,
  ) -> Select {
    params.retain(|k| match entry.as_ref() {
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
      .unwrap_or_else(|| panic!("{:?} did not declare a dependency on {:?}", edges, product));
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
        throw(format!(
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
    match self.entry.as_ref() {
      &rule_graph::Entry::WithDeps(wd) => match wd.as_ref() {
        rule_graph::EntryWithDeps::Inner(ref inner) => match inner.rule() {
          &tasks::Rule::Task(ref task) => {
            context
              .get(Task {
                params: self.params.clone(),
                task: *task,
                entry: self.entry,
                side_effected: Arc::new(AtomicBool::new(false)),
              })
              .await
          }
          &Rule::Intrinsic(ref intrinsic) => {
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
        },
        &rule_graph::EntryWithDeps::Root(_) => {
          panic!("Not a runtime-executable entry! {:?}", self.entry)
        }
      },
      &rule_graph::Entry::Param(type_id) => {
        if let Some(key) = self.params.find(type_id) {
          Ok(key.to_value())
        } else {
          Err(throw(format!(
            "Expected a Param of type {} to be present.",
            type_id
          )))
        }
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

pub fn lift_directory_digest(digest: &PyAny) -> Result<DirectoryDigest, String> {
  let py_digest: externs::fs::PyDigest = digest.extract().map_err(|e| format!("{}", e))?;
  Ok(py_digest.0)
}

pub fn lift_file_digest(digest: &PyAny) -> Result<hashing::Digest, String> {
  let py_file_digest: externs::fs::PyFileDigest = digest.extract().map_err(|e| format!("{}", e))?;
  Ok(py_file_digest.0)
}

/// A Node that represents a process to execute.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct ExecuteProcess {
  process: Process,
}

impl ExecuteProcess {
  async fn lift_process_input_digests(
    store: &Store,
    value: &Value,
  ) -> Result<InputDigests, String> {
    let input_digests_fut: Result<_, String> = Python::with_gil(|py| {
      let value = (**value).as_ref(py);
      let input_files = lift_directory_digest(externs::getattr(value, "input_digest").unwrap())
        .map_err(|err| format!("Error parsing input_digest {}", err))?;
      let immutable_inputs =
        externs::getattr_from_str_frozendict::<&PyAny>(value, "immutable_input_digests")
          .into_iter()
          .map(|(path, digest)| Ok((RelativePath::new(path)?, lift_directory_digest(digest)?)))
          .collect::<Result<BTreeMap<_, _>, String>>()?;
      let use_nailgun = externs::getattr::<Vec<String>>(value, "use_nailgun")
        .unwrap()
        .into_iter()
        .map(RelativePath::new)
        .collect::<Result<Vec<_>, _>>()?;

      Ok(InputDigests::new(
        store,
        input_files,
        immutable_inputs,
        use_nailgun,
      ))
    });

    input_digests_fut?
      .await
      .map_err(|e| format!("Failed to merge input digests for process: {}", e))
  }

  fn lift_process(value: &PyAny, input_digests: InputDigests) -> Result<Process, String> {
    let env = externs::getattr_from_str_frozendict(value, "env");
    let working_directory = match externs::getattr_as_optional_string(value, "working_directory") {
      None => None,
      Some(dir) => Some(RelativePath::new(dir)?),
    };

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
    let py_level = externs::getattr(value, "level").unwrap();
    let level = externs::val_to_log_level(py_level)?;

    let append_only_caches =
      externs::getattr_from_str_frozendict::<&str>(value, "append_only_caches")
        .into_iter()
        .map(|(name, dest)| Ok((CacheName::new(name)?, RelativePath::new(dest)?)))
        .collect::<Result<_, String>>()?;

    let jdk_home = externs::getattr_as_optional_string(value, "jdk_home").map(PathBuf::from);

    let execution_slot_variable =
      externs::getattr_as_optional_string(value, "execution_slot_variable");

    let concurrency_available: usize = externs::getattr(value, "concurrency_available").unwrap();

    let cache_scope: ProcessCacheScope = {
      let cache_scope_enum = externs::getattr(value, "cache_scope").unwrap();
      externs::getattr::<String>(cache_scope_enum, "name")
        .unwrap()
        .try_into()?
    };

    let platform_constraint =
      if let Some(p) = externs::getattr_as_optional_string(value, "platform") {
        Some(Platform::try_from(p)?)
      } else {
        None
      };

    Ok(process_execution::Process {
      argv: externs::getattr(value, "argv").unwrap(),
      env,
      working_directory,
      input_digests,
      output_files,
      output_directories,
      timeout,
      description,
      level,
      append_only_caches,
      jdk_home,
      platform_constraint,
      execution_slot_variable,
      concurrency_available,
      cache_scope,
    })
  }

  pub async fn lift(store: &Store, value: Value) -> Result<Self, String> {
    let input_digests = Self::lift_process_input_digests(store, &value).await?;
    let process = Python::with_gil(|py| Self::lift_process((*value).as_ref(py), input_digests))?;
    Ok(Self { process })
  }
}

impl From<ExecuteProcess> for NodeKey {
  fn from(n: ExecuteProcess) -> Self {
    NodeKey::ExecuteProcess(Box::new(n))
  }
}

#[async_trait]
impl WrappedNode for ExecuteProcess {
  type Item = ProcessResult;

  async fn run_wrapped_node(
    self,
    context: Context,
    workunit: &mut RunningWorkunit,
  ) -> NodeResult<ProcessResult> {
    let request = self.process;

    let command_runner = &context.core.command_runner;

    let execution_context = process_execution::Context::new(
      context.session.workunit_store(),
      context.session.build_id().to_string(),
      context.session.run_id(),
    );

    let res = command_runner
      .run(execution_context, workunit, request.clone())
      .await
      .map_err(throw)?;

    let definition = serde_json::to_string(&request)
      .map_err(|e| throw(format!("Failed to serialize process: {}", e)))?;
    workunit.update_metadata(|initial| {
      initial.map(|(initial, level)| {
        (
          WorkunitMetadata {
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
          },
          level,
        )
      })
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
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct ProcessResult(pub process_execution::FallibleProcessResultWithPlatform);

///
/// A Node that represents reading the destination of a symlink (non-recursively).
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct ReadLink(Link);

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
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
      .map_err(|e| throw(format!("{}", e)))?;
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
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
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
      .map_err(throw)
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
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
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
      .map_err(|e| throw(format!("{}", e)))?;
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
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
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
      .map_err(|e| throw(format!("{}", e)))
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
    let path_globs = self.path_globs.parse().map_err(throw)?;
    let path_stats = Self::create(context, path_globs).await?;
    Ok(Arc::new(path_stats))
  }
}

impl From<Paths> for NodeKey {
  fn from(n: Paths) -> Self {
    NodeKey::Paths(n)
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct SessionValues;

#[async_trait]
impl WrappedNode for SessionValues {
  type Item = Value;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Value> {
    Ok(Value::new(context.session.session_values()))
  }
}

impl From<SessionValues> for NodeKey {
  fn from(n: SessionValues) -> Self {
    NodeKey::SessionValues(n)
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct RunId;

#[async_trait]
impl WrappedNode for RunId {
  type Item = Value;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<Value> {
    let gil = Python::acquire_gil();
    let py = gil.python();
    Ok(externs::unsafe_call(
      py,
      context.core.types.run_id,
      &[externs::store_u64(py, context.session.run_id().0 as u64)],
    ))
  }
}

impl From<RunId> for NodeKey {
  fn from(n: RunId) -> Self {
    NodeKey::RunId(n)
  }
}

///
/// A Node that captures an store::Snapshot for a PathGlobs subject.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Snapshot {
  path_globs: PathGlobs,
}

impl Snapshot {
  pub fn from_path_globs(path_globs: PathGlobs) -> Snapshot {
    Snapshot { path_globs }
  }

  pub fn lift_path_globs(item: &PyAny) -> Result<PathGlobs, String> {
    let globs: Vec<String> = externs::getattr(item, "globs").unwrap();
    let description_of_origin = externs::getattr_as_optional_string(item, "description_of_origin");

    let glob_match_error_behavior = externs::getattr(item, "glob_match_error_behavior").unwrap();
    let failure_behavior: String = externs::getattr(glob_match_error_behavior, "value").unwrap();
    let strict_glob_matching =
      StrictGlobMatching::create(failure_behavior.as_str(), description_of_origin)?;

    let conjunction_obj = externs::getattr(item, "conjunction").unwrap();
    let conjunction_string: String = externs::getattr(conjunction_obj, "value").unwrap();
    let conjunction = GlobExpansionConjunction::create(&conjunction_string)?;
    Ok(PathGlobs::new(globs, strict_glob_matching, conjunction))
  }

  pub fn lift_prepared_path_globs(item: &PyAny) -> Result<PreparedPathGlobs, String> {
    let path_globs = Snapshot::lift_path_globs(item)?;
    path_globs
      .parse()
      .map_err(|e| format!("Failed to parse PathGlobs for globs({:?}): {}", item, e))
  }

  pub fn store_directory_digest(py: Python, item: DirectoryDigest) -> Result<Value, String> {
    let py_digest = Py::new(py, externs::fs::PyDigest(item)).map_err(|e| format!("{}", e))?;
    Ok(Value::new(py_digest.into_py(py)))
  }

  pub fn store_file_digest(py: Python, item: hashing::Digest) -> Result<Value, String> {
    let py_file_digest =
      Py::new(py, externs::fs::PyFileDigest(item)).map_err(|e| format!("{}", e))?;
    Ok(Value::new(py_file_digest.into_py(py)))
  }

  pub fn store_snapshot(py: Python, item: store::Snapshot) -> Result<Value, String> {
    let py_snapshot = Py::new(py, externs::fs::PySnapshot(item)).map_err(|e| format!("{}", e))?;
    Ok(Value::new(py_snapshot.into_py(py)))
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
        Self::store_file_digest(py, item.digest)?,
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
  type Item = store::Snapshot;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<store::Snapshot> {
    let path_globs = self.path_globs.parse().map_err(throw)?;

    // We rely on Context::expand_globs to track dependencies for scandirs,
    // and `context.get(DigestFile)` to track dependencies for file digests.
    let path_stats = context
      .expand_globs(path_globs, unmatched_globs_additional_context())
      .map_err(|e| throw(format!("{}", e)))
      .await?;

    store::Snapshot::from_path_stats(context.clone(), path_stats)
      .map_err(|e| throw(format!("Snapshot failed: {}", e)))
      .await
  }
}

impl From<Snapshot> for NodeKey {
  fn from(n: Snapshot) -> Self {
    NodeKey::Snapshot(n)
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
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
  type Item = store::Snapshot;

  async fn run_wrapped_node(
    self,
    context: Context,
    _workunit: &mut RunningWorkunit,
  ) -> NodeResult<store::Snapshot> {
    let (url_str, expected_digest) = Python::with_gil(|py| {
      let py_download_file_val = self.0.to_value();
      let py_download_file = (*py_download_file_val).as_ref(py);
      let url_str: String = externs::getattr(py_download_file, "url").unwrap();
      let py_file_digest: PyFileDigest =
        externs::getattr(py_download_file, "expected_digest").unwrap();
      let res: NodeResult<(String, Digest)> = Ok((url_str, py_file_digest.0));
      res
    })?;
    let url = Url::parse(&url_str)
      .map_err(|err| throw(format!("Error parsing URL {}: {}", url_str, err)))?;
    self
      .load_or_download(context.core, url, expected_digest)
      .await
      .map_err(throw)
  }
}

impl From<DownloadedFile> for NodeKey {
  fn from(n: DownloadedFile) -> Self {
    NodeKey::DownloadedFile(n)
  }
}

#[derive(DeepSizeOf, Derivative, Clone)]
#[derivative(Eq, PartialEq, Hash)]
pub struct Task {
  pub params: Params,
  task: Intern<tasks::Task>,
  // The Params and the Task struct are sufficient to uniquely identify it.
  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  entry: Intern<rule_graph::Entry<Rule>>,
  // Does not affect the identity of the Task.
  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  side_effected: Arc<AtomicBool>,
}

impl Task {
  async fn gen_get(
    context: &Context,
    workunit: &mut RunningWorkunit,
    params: &Params,
    entry: Intern<rule_graph::Entry<Rule>>,
    gets: Vec<externs::Get>,
  ) -> NodeResult<Vec<Value>> {
    // While waiting for dependencies, mark the workunit for this Task blocked.
    let _blocking_token = workunit.blocking();
    let get_futures = gets
      .into_iter()
      .map(|get| {
        let context = context.clone();
        let mut params = params.clone();
        async move {
          let dependency_key = selectors::DependencyKey::JustGet(selectors::Get {
            output: get.output,
            input: *get.input.type_id(),
          });
          params.put(get.input.clone());

          let edges = context
            .core
            .rule_graph
            .edges_for_inner(&entry)
            .ok_or_else(|| throw(format!("No edges for task {:?} exist!", entry)))?;

          // See if there is a Get: otherwise, a union (which is executed as a Query).
          // See #12934 for further cleanup of this API.
          let select = edges
            .entry_for(&dependency_key)
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
                throw(format!(
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
                throw(format!(
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
    entry: Intern<rule_graph::Entry<Rule>>,
    generator: Value,
  ) -> NodeResult<(Value, TypeId)> {
    let mut input = {
      let gil = Python::acquire_gil();
      Value::from(gil.python().None())
    };
    loop {
      let context = context.clone();
      let params = params.clone();
      let response = Python::with_gil(|py| externs::generator_send(py, &generator, &input))?;
      match response {
        externs::GeneratorResponse::Get(get) => {
          let values = Self::gen_get(&context, workunit, &params, entry, vec![get]).await?;
          input = values.into_iter().next().unwrap();
        }
        externs::GeneratorResponse::GetMulti(gets) => {
          let values = Self::gen_get(&context, workunit, &params, entry, gets).await?;
          let gil = Python::acquire_gil();
          input = externs::store_tuple(gil.python(), values);
        }
        externs::GeneratorResponse::Break(val, type_id) => {
          break Ok((val, type_id));
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
      self.task.func, self.params, self.task.product, self.task.cacheable,
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
          .iter()
          .map(|type_id| {
            Select::new_from_edges(params.clone(), *type_id, edges).run(context.clone())
          })
          .collect::<Vec<_>>(),
      )
      .await?
    };

    let func = self.task.func.clone();

    let (mut result_val, mut result_type) =
      maybe_side_effecting(self.task.side_effecting, &self.side_effected, async move {
        Python::with_gil(|py| {
          let func_val = func.0.to_value();
          let func = (*func_val).as_ref(py);
          externs::call_function(func, &deps)
            .map(|res| {
              let type_id = TypeId::new(res.get_type());
              let val = Value::new(res.into_py(py));
              (val, type_id)
            })
            .map_err(Failure::from_py_err)
        })
      })
      .await?;

    if result_type == context.core.types.coroutine {
      let (new_val, new_type) = maybe_side_effecting(
        self.task.side_effecting,
        &self.side_effected,
        Self::generate(&context, workunit, params, self.entry, result_val),
      )
      .await?;
      result_val = new_val;
      result_type = new_type;
    }

    if result_type != self.task.product {
      return Err(throw(format!(
        "{:?} returned a result value that did not satisfy its constraints: {:?}",
        self.task.func, result_val
      )));
    }

    if self.task.engine_aware_return_type {
      let gil = Python::acquire_gil();
      let py = gil.python();
      EngineAwareReturnType::update_workunit(workunit, (*result_val).as_ref(py))
    };

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
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub enum NodeKey {
  DigestFile(DigestFile),
  DownloadedFile(DownloadedFile),
  ExecuteProcess(Box<ExecuteProcess>),
  ReadLink(ReadLink),
  Scandir(Scandir),
  Select(Box<Select>),
  Snapshot(Snapshot),
  Paths(Paths),
  SessionValues(SessionValues),
  RunId(RunId),
  Task(Box<Task>),
}

impl NodeKey {
  fn product_str(&self) -> String {
    match self {
      &NodeKey::ExecuteProcess(..) => "ProcessResult".to_string(),
      &NodeKey::DownloadedFile(..) => "DownloadedFile".to_string(),
      &NodeKey::Select(ref s) => format!("{}", s.product),
      &NodeKey::SessionValues(_) => "SessionValues".to_string(),
      &NodeKey::RunId(_) => "RunId".to_string(),
      &NodeKey::Task(ref t) => format!("{}", t.task.product),
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
      &NodeKey::ExecuteProcess { .. }
      | &NodeKey::Select { .. }
      | &NodeKey::SessionValues { .. }
      | &NodeKey::RunId { .. }
      | &NodeKey::Snapshot { .. }
      | &NodeKey::Paths { .. }
      | &NodeKey::Task { .. }
      | &NodeKey::DownloadedFile { .. } => None,
    }
  }

  fn workunit_level(&self) -> Level {
    match self {
      NodeKey::Task(ref task) => task.task.display_info.level,
      NodeKey::ExecuteProcess(..) => {
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
  pub fn workunit_name(&self) -> &'static str {
    match self {
      NodeKey::Task(ref task) => &task.task.as_ref().display_info.name,
      NodeKey::ExecuteProcess(..) => "process",
      NodeKey::Snapshot(..) => "snapshot",
      NodeKey::Paths(..) => "paths",
      NodeKey::DigestFile(..) => "digest_file",
      NodeKey::DownloadedFile(..) => "downloaded_file",
      NodeKey::ReadLink(..) => "read_link",
      NodeKey::Scandir(..) => "scandir",
      NodeKey::Select(..) => "select",
      NodeKey::SessionValues(..) => "session_values",
      NodeKey::RunId(..) => "run_id",
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
      NodeKey::ExecuteProcess(epr) => {
        // NB: See Self::workunit_level for more information on why this is prefixed.
        Some(format!("Scheduling: {}", epr.process.description))
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
      NodeKey::RunId(..) => None,
    }
  }

  ///
  /// Filters the given Params to those which are subtypes of EngineAwareParameter.
  ///
  fn engine_aware_params<'a>(
    context: Context,
    py: Python<'a>,
    params: &'a Params,
  ) -> impl Iterator<Item = Value> + 'a {
    let engine_aware_param_ty = context.core.types.engine_aware_parameter.as_py_type(py);
    params.keys().filter_map(move |key| {
      if key
        .type_id()
        .as_py_type(py)
        .is_subclass(engine_aware_param_ty)
        .unwrap_or(false)
      {
        Some(key.to_value())
      } else {
        None
      }
    })
  }
}

#[async_trait]
impl Node for NodeKey {
  type Context = Context;

  type Item = NodeOutput;
  type Error = Failure;

  async fn run(self, context: Context) -> Result<NodeOutput, Failure> {
    let workunit_name = self.workunit_name();
    let params = match &self {
      NodeKey::Task(ref task) => task.params.clone(),
      _ => Params::default(),
    };
    let context2 = context.clone();

    in_workunit!(
      workunit_name,
      self.workunit_level(),
      desc = self.user_facing_name(),
      user_metadata = {
        let gil = Python::acquire_gil();
        let py = gil.python();
        Self::engine_aware_params(context.clone(), py, &params)
          .flat_map(|val| EngineAwareParameter::metadata((*val).as_ref(py)))
          .collect()
      },
      |workunit| async move {
        // To avoid races, we must ensure that we have installed a watch for the subject before
        // executing the node logic. But in case of failure, we wait to see if the Node itself
        // fails, and prefer that error message if so (because we have little control over the
        // error messages of the watch API).
        let maybe_watch =
          if let Some((path, watcher)) = self.fs_subject().zip(context.core.watcher.as_ref()) {
            let abs_path = context.core.build_root.join(path);
            watcher
              .watch(abs_path)
              .map_err(|e| Context::mk_error(&e))
              .await
          } else {
            Ok(())
          };

        let mut result = match self {
          NodeKey::DigestFile(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::FileDigest)
              .await
          }
          NodeKey::DownloadedFile(n) => {
            n.run_wrapped_node(context, workunit)
              .map_ok(NodeOutput::Snapshot)
              .await
          }
          NodeKey::ExecuteProcess(n) => {
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
              .map_ok(NodeOutput::Snapshot)
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
          NodeKey::RunId(n) => {
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
            Self::engine_aware_params(context2, py, &params)
              .filter_map(|val| EngineAwareParameter::debug_hint((*val).as_ref(py)))
              .collect()
          };
          let failure_name = if displayable_param_names.is_empty() {
            name.to_owned()
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
      &NodeKey::SessionValues(_) | &NodeKey::RunId(_) => false,
      _ => true,
    }
  }

  fn cacheable_item(&self, output: &NodeOutput) -> bool {
    match (self, output) {
      (NodeKey::ExecuteProcess(ref ep), NodeOutput::ProcessResult(ref process_result)) => {
        match ep.process.cache_scope {
          ProcessCacheScope::Always | ProcessCacheScope::PerRestartAlways => true,
          ProcessCacheScope::Successful | ProcessCacheScope::PerRestartSuccessful => {
            process_result.0.exit_code == 0
          }
          ProcessCacheScope::PerSession => false,
        }
      }
      (NodeKey::Task(ref t), NodeOutput::Value(ref v)) if t.task.engine_aware_return_type => {
        let gil = Python::acquire_gil();
        let py = gil.python();
        EngineAwareReturnType::is_cacheable((**v).as_ref(py)).unwrap_or(true)
      }
      _ => true,
    }
  }

  fn cyclic_error(path: &[&NodeKey]) -> Failure {
    let mut path = path.iter().map(|n| n.to_string()).collect::<Vec<_>>();
    if !path.is_empty() {
      path[0] += " <-";
      path.push(path[0].clone());
    }
    let gil = Python::acquire_gil();
    let url = externs::doc_url(
      gil.python(),
      "targets#dependencies-and-dependency-inference",
    );
    throw(format!(
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

impl Display for NodeKey {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    match self {
      &NodeKey::DigestFile(ref s) => write!(f, "DigestFile({})", s.0.path.display()),
      &NodeKey::DownloadedFile(ref s) => write!(f, "DownloadedFile({})", s.0),
      &NodeKey::ExecuteProcess(ref s) => {
        write!(f, "Process({})", s.process.description)
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
            .filter_map(|k| {
              EngineAwareParameter::debug_hint(k.to_value().clone_ref(py).into_ref(py))
            })
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
      &NodeKey::RunId(_) => write!(f, "RunId"),
      &NodeKey::Paths(ref s) => write!(f, "Paths({})", s.path_globs),
    }
  }
}

impl NodeError for Failure {
  fn invalidated() -> Failure {
    Failure::Invalidated
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub enum NodeOutput {
  FileDigest(hashing::Digest),
  Snapshot(store::Snapshot),
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
      NodeOutput::FileDigest(d) => vec![*d],
      NodeOutput::Snapshot(s) => {
        // TODO: Callers should maybe be adapted for the fact that these nodes will now return
        // transitive lists of digests (since lease extension might be operating recursively
        // too). #13112.
        let dd: DirectoryDigest = s.clone().into();
        dd.digests()
      }
      NodeOutput::ProcessResult(p) => {
        let mut digests = p.0.output_directory.digests();
        digests.push(p.0.stdout_digest);
        digests.push(p.0.stderr_digest);
        digests
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
      NodeOutput::FileDigest(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeOutput> for store::Snapshot {
  type Error = ();

  fn try_from(nr: NodeOutput) -> Result<Self, ()> {
    match nr {
      NodeOutput::Snapshot(v) => Ok(v),
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
