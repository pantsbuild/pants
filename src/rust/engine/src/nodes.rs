// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, BTreeSet};
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
use pyo3::prelude::{Py, PyAny, PyErr, Python};
use pyo3::IntoPy;
use url::Url;

use crate::context::{Context, Core, SessionCore};
use crate::downloads;
use crate::externs;
use crate::python::{display_sorted_in_parens, throw, Failure, Key, Params, TypeId, Value};
use crate::tasks::{self, Rule};
use fs::{
  self, DigestEntry, Dir, DirectoryDigest, DirectoryListing, File, FileContent, FileEntry,
  GlobExpansionConjunction, GlobMatching, Link, PathGlobs, PreparedPathGlobs, RelativePath,
  StrictGlobMatching, SymlinkBehavior, SymlinkEntry, Vfs,
};
use process_execution::{
  self, CacheName, InputDigests, Process, ProcessCacheScope, ProcessExecutionStrategy,
  ProcessResultSource,
};

use crate::externs::engine_aware::{EngineAwareParameter, EngineAwareReturnType};
use crate::externs::fs::PyFileDigest;
use crate::externs::{GeneratorInput, GeneratorResponse};
use graph::{CompoundNode, Node, NodeError};
use hashing::Digest;
use rule_graph::{DependencyKey, Query};
use store::{self, Store, StoreError, StoreFileByDigest};
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
/// A Node that selects a product for some Params.
///
/// NB: This is a Node so that it can be used as a root in the graph, but it does not implement
/// CompoundNode, because it should never be requested as a Node using context.get. Select is a thin
/// proxy to other Node types (which it requests using context.get), and memoizing it would be
/// redundant.
///
/// Instead, use `Select::run_node` to run the Select logic without memoizing it.
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
      rule_graph::Entry::Param(type_id) => type_id == k.type_id(),
      rule_graph::Entry::WithDeps(with_deps) => with_deps.params().contains(k.type_id()),
    });
    Select {
      params,
      product,
      entry,
    }
  }

  pub fn new_from_edges(
    params: Params,
    dependency_key: &DependencyKey<TypeId>,
    edges: &rule_graph::RuleEdges<Rule>,
  ) -> Select {
    let entry = edges
      .entry_for(dependency_key)
      .unwrap_or_else(|| panic!("{edges:?} did not declare a dependency on {dependency_key:?}"));
    Select::new(params, dependency_key.product(), entry)
  }

  fn reenter<'a>(
    &self,
    context: Context,
    query: &'a Query<TypeId>,
  ) -> BoxFuture<'a, NodeResult<Value>> {
    let edges = context
      .core
      .rule_graph
      .find_root(query.params.iter().cloned(), query.product)
      .map(|(_, edges)| edges);

    let params = self.params.clone();
    async move {
      let edges = edges?;
      Select::new_from_edges(params, &DependencyKey::new(query.product), &edges)
        .run_node(context)
        .await
    }
    .boxed()
  }

  fn select_product<'a>(
    &self,
    context: Context,
    dependency_key: &'a DependencyKey<TypeId>,
    caller_description: &str,
  ) -> BoxFuture<'a, NodeResult<Value>> {
    let edges = context
      .core
      .rule_graph
      .edges_for_inner(&self.entry)
      .ok_or_else(|| {
        throw(format!(
          "Tried to request {dependency_key} for {caller_description} but found no edges"
        ))
      });
    let params = self.params.clone();
    async move {
      let edges = edges?;
      Select::new_from_edges(params, dependency_key, &edges)
        .run_node(context)
        .await
    }
    .boxed()
  }

  async fn run_node(self, context: Context) -> NodeResult<Value> {
    match self.entry.as_ref() {
      &rule_graph::Entry::WithDeps(wd) => match wd.as_ref() {
        rule_graph::EntryWithDeps::Rule(ref rule) => match rule.rule() {
          tasks::Rule::Task(task) => {
            context
              .get(Task {
                params: self.params.clone(),
                task: *task,
                entry: self.entry,
                side_effected: Arc::new(AtomicBool::new(false)),
              })
              .await
          }
          Rule::Intrinsic(intrinsic) => {
            let values = future::try_join_all(
              intrinsic
                .inputs
                .iter()
                .map(|dependency_key| {
                  self.select_product(context.clone(), dependency_key, "intrinsic")
                })
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
        rule_graph::EntryWithDeps::Reentry(reentry) => {
          // TODO: Actually using the `RuleEdges` of this entry to compute inputs is not
          // implemented: doing so would involve doing something similar to what we do for
          // intrinsics above, and waiting to compute inputs before executing the query here.
          //
          // That doesn't block using a singleton to provide an API type, but it would block a more
          // complex use case.
          //
          // see https://github.com/pantsbuild/pants/issues/16751
          self.reenter(context, &reentry.query).await
        }
        &rule_graph::EntryWithDeps::Root(_) => {
          panic!("Not a runtime-executable entry! {:?}", self.entry)
        }
      },
      &rule_graph::Entry::Param(type_id) => {
        if let Some(key) = self.params.find(type_id) {
          Ok(key.to_value())
        } else {
          Err(throw(format!(
            "Expected a Param of type {} to be present, but had only: {}",
            type_id, self.params,
          )))
        }
      }
    }
  }
}

impl From<Select> for NodeKey {
  fn from(n: Select) -> Self {
    NodeKey::Select(Box::new(n))
  }
}

pub fn lift_directory_digest(digest: &PyAny) -> Result<DirectoryDigest, String> {
  let py_digest: externs::fs::PyDigest = digest.extract().map_err(|e| format!("{e}"))?;
  Ok(py_digest.0)
}

pub fn lift_file_digest(digest: &PyAny) -> Result<hashing::Digest, String> {
  let py_file_digest: externs::fs::PyFileDigest = digest.extract().map_err(|e| format!("{e}"))?;
  Ok(py_file_digest.0)
}

/// A Node that represents a process to execute.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct ExecuteProcess {
  pub process: Process,
}

impl ExecuteProcess {
  async fn lift_process_input_digests(
    store: &Store,
    value: &Value,
  ) -> Result<InputDigests, StoreError> {
    let input_digests_fut: Result<_, String> = Python::with_gil(|py| {
      let value = (**value).as_ref(py);
      let input_files = lift_directory_digest(externs::getattr(value, "input_digest")?)
        .map_err(|err| format!("Error parsing input_digest {err}"))?;
      let immutable_inputs =
        externs::getattr_from_str_frozendict::<&PyAny>(value, "immutable_input_digests")
          .into_iter()
          .map(|(path, digest)| Ok((RelativePath::new(path)?, lift_directory_digest(digest)?)))
          .collect::<Result<BTreeMap<_, _>, String>>()?;
      let use_nailgun = externs::getattr::<Vec<String>>(value, "use_nailgun")?
        .into_iter()
        .map(RelativePath::new)
        .collect::<Result<BTreeSet<_>, _>>()?;

      Ok(InputDigests::new(
        store,
        input_files,
        immutable_inputs,
        use_nailgun,
      ))
    });

    input_digests_fut?
      .await
      .map_err(|e| e.enrich("Failed to merge input digests for process"))
  }

  fn lift_process_fields(
    value: &PyAny,
    input_digests: InputDigests,
    process_config: externs::process::PyProcessExecutionEnvironment,
  ) -> Result<Process, StoreError> {
    let env = externs::getattr_from_str_frozendict(value, "env");

    let working_directory = externs::getattr_as_optional_string(value, "working_directory")
      .map_err(|e| format!("Failed to get `working_directory` from field: {e}"))?
      .map(RelativePath::new)
      .transpose()?;

    let output_files = externs::getattr::<Vec<String>>(value, "output_files")?
      .into_iter()
      .map(RelativePath::new)
      .collect::<Result<_, _>>()?;

    let output_directories = externs::getattr::<Vec<String>>(value, "output_directories")?
      .into_iter()
      .map(RelativePath::new)
      .collect::<Result<_, _>>()?;

    let timeout_in_seconds: f64 = externs::getattr(value, "timeout_seconds")?;

    let timeout = if timeout_in_seconds < 0.0 {
      None
    } else {
      Some(Duration::from_millis((timeout_in_seconds * 1000.0) as u64))
    };

    let description: String = externs::getattr(value, "description")?;

    let py_level = externs::getattr(value, "level")?;

    let level = externs::val_to_log_level(py_level)?;

    let append_only_caches =
      externs::getattr_from_str_frozendict::<&str>(value, "append_only_caches")
        .into_iter()
        .map(|(name, dest)| Ok((CacheName::new(name)?, RelativePath::new(dest)?)))
        .collect::<Result<_, String>>()?;

    let jdk_home = externs::getattr_as_optional_string(value, "jdk_home")
      .map_err(|e| format!("Failed to get `jdk_home` from field: {e}"))?
      .map(PathBuf::from);

    let execution_slot_variable =
      externs::getattr_as_optional_string(value, "execution_slot_variable")
        .map_err(|e| format!("Failed to get `execution_slot_variable` for field: {e}"))?;

    let concurrency_available: usize = externs::getattr(value, "concurrency_available")?;

    let cache_scope: ProcessCacheScope = {
      let cache_scope_enum = externs::getattr(value, "cache_scope")?;
      externs::getattr::<String>(cache_scope_enum, "name")?.try_into()?
    };

    let remote_cache_speculation_delay = std::time::Duration::from_millis(
      externs::getattr::<i32>(value, "remote_cache_speculation_delay_millis")
        .map_err(|e| format!("Failed to get `name` for field: {e}"))? as u64,
    );

    let extra = externs::getattr_from_str_frozendict(value, "extra");

    Ok(Process {
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
      execution_slot_variable,
      concurrency_available,
      cache_scope,
      execution_environment: process_config.environment,
      remote_cache_speculation_delay,
      extra,
    })
  }

  pub async fn lift(
    store: &Store,
    value: Value,
    process_config: externs::process::PyProcessExecutionEnvironment,
  ) -> Result<Self, StoreError> {
    let input_digests = Self::lift_process_input_digests(store, &value).await?;
    let process = Python::with_gil(|py| {
      Self::lift_process_fields((*value).as_ref(py), input_digests, process_config)
    })?;
    Ok(Self { process })
  }

  async fn run_node(
    self,
    context: Context,
    workunit: &mut RunningWorkunit,
    backtrack_level: usize,
  ) -> NodeResult<ProcessResult> {
    let request = self.process;

    let command_runner = context
      .core
      .command_runners
      .get(backtrack_level)
      .ok_or_else(|| {
        // NB: We only backtrack for a Process if it produces a Digest which cannot be consumed
        // from disk: if we've fallen all the way back to local execution, and even that
        // produces an unreadable Digest, then there is a fundamental implementation issue.
        throw(format!(
          "Process {request:?} produced an invalid result on all configured command runners."
        ))
      })?;

    let execution_context = process_execution::Context::new(
      context.session.workunit_store(),
      context.session.build_id().to_string(),
      context.session.run_id(),
      context.session.tail_tasks(),
    );

    let res = command_runner
      .run(execution_context, workunit, request.clone())
      .await?;

    let definition = serde_json::to_string(&request)
      .map_err(|e| throw(format!("Failed to serialize process: {e}")))?;
    workunit.update_metadata(|initial| {
      initial.map(|(initial, level)| {
        let mut user_metadata = Vec::with_capacity(7);
        user_metadata.push((
          "definition".to_string(),
          UserMetadataItem::String(definition),
        ));
        user_metadata.push((
          "source".to_string(),
          UserMetadataItem::String(format!("{:?}", res.metadata.source)),
        ));
        user_metadata.push((
          "exit_code".to_string(),
          UserMetadataItem::Int(res.exit_code as i64),
        ));
        user_metadata.push((
          "environment_type".to_string(),
          UserMetadataItem::String(res.metadata.environment.strategy.strategy_type().to_owned()),
        ));
        if let Some(environment_name) = res.metadata.environment.name.clone() {
          user_metadata.push((
            "environment_name".to_string(),
            UserMetadataItem::String(environment_name),
          ));
        }
        if let Some(total_elapsed) = res.metadata.total_elapsed {
          user_metadata.push((
            "total_elapsed_ms".to_string(),
            UserMetadataItem::Int(Duration::from(total_elapsed).as_millis() as i64),
          ));
        }
        if let Some(saved_by_cache) = res.metadata.saved_by_cache {
          user_metadata.push((
            "saved_by_cache_ms".to_string(),
            UserMetadataItem::Int(Duration::from(saved_by_cache).as_millis() as i64),
          ));
        }

        (
          WorkunitMetadata {
            stdout: Some(res.stdout_digest),
            stderr: Some(res.stderr_digest),
            user_metadata,
            ..initial
          },
          level,
        )
      })
    });
    if let Some(total_elapsed) = res.metadata.total_elapsed {
      let total_elapsed = Duration::from(total_elapsed).as_millis() as u64;
      match (res.metadata.source, &res.metadata.environment.strategy) {
        (ProcessResultSource::Ran, ProcessExecutionStrategy::Local) => {
          workunit.increment_counter(Metric::LocalProcessTotalTimeRunMs, total_elapsed);
          context
            .session
            .workunit_store()
            .record_observation(ObservationMetric::LocalProcessTimeRunMs, total_elapsed);
        }
        (ProcessResultSource::Ran, ProcessExecutionStrategy::RemoteExecution { .. }) => {
          workunit.increment_counter(Metric::RemoteProcessTotalTimeRunMs, total_elapsed);
          context
            .session
            .workunit_store()
            .record_observation(ObservationMetric::RemoteProcessTimeRunMs, total_elapsed);
        }
        _ => {}
      }
    }

    if backtrack_level > 0 {
      // TODO: This message is symmetrical to the "Making attempt {} to backtrack and retry {}"
      // message in `context.rs`, but both of them are effectively debug output. They should be
      // quieted down as part of https://github.com/pantsbuild/pants/issues/15867 once all bugs
      // have been shaken out.
      log::info!(
        "On backtrack attempt {} for `{}`, produced: {:?}",
        backtrack_level,
        request.description,
        res.output_directory.digests()
      );
    }

    Ok(ProcessResult {
      result: res,
      backtrack_level,
    })
  }
}

impl From<ExecuteProcess> for NodeKey {
  fn from(n: ExecuteProcess) -> Self {
    NodeKey::ExecuteProcess(Box::new(n))
  }
}

impl CompoundNode<NodeKey> for ExecuteProcess {
  type Item = ProcessResult;
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct ProcessResult {
  pub result: process_execution::FallibleProcessResultWithPlatform,
  /// The backtrack_level which produced this result. If a Digest from a particular result is
  /// missing, the next attempt needs to use a higher level of backtracking (i.e.: remove more
  /// caches).
  pub backtrack_level: usize,
}

///
/// A Node that represents reading the destination of a symlink (non-recursively).
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct ReadLink(Link);

impl ReadLink {
  async fn run_node(self, context: Context) -> NodeResult<LinkDest> {
    let node = self;
    let link_dest = context
      .core
      .vfs
      .read_link(&node.0)
      .await
      .map_err(|e| throw(format!("{e}")))?;
    Ok(LinkDest(link_dest))
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct LinkDest(PathBuf);

impl CompoundNode<NodeKey> for ReadLink {
  type Item = LinkDest;
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

impl DigestFile {
  async fn run_node(self, context: Context) -> NodeResult<hashing::Digest> {
    let path = context.core.vfs.file_path(&self.0);
    context
      .core
      .store()
      .store_file(true, false, path)
      .map_err(throw)
      .await
  }
}

impl CompoundNode<NodeKey> for DigestFile {
  type Item = hashing::Digest;
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

impl Scandir {
  async fn run_node(self, context: Context) -> NodeResult<Arc<DirectoryListing>> {
    let directory_listing = context
      .core
      .vfs
      .scandir(self.0)
      .await
      .map_err(|e| throw(format!("{e}")))?;
    Ok(Arc::new(directory_listing))
  }
}

impl CompoundNode<NodeKey> for Scandir {
  type Item = Arc<DirectoryListing>;
}

impl From<Scandir> for NodeKey {
  fn from(n: Scandir) -> Self {
    NodeKey::Scandir(n)
  }
}

pub fn unmatched_globs_additional_context() -> Option<String> {
  let url = Python::with_gil(|py| {
    externs::doc_url(
      py,
      "troubleshooting#pants-cannot-find-a-file-in-your-project",
    )
  });
  Some(format!(
    "\n\nDo the file(s) exist? If so, check if the file(s) are in your `.gitignore` or the global \
    `pants_ignore` option, which may result in Pants not being able to see the file(s) even though \
    they exist on disk. Refer to {url}."
  ))
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct SessionValues;

impl SessionValues {
  async fn run_node(self, context: Context) -> NodeResult<Value> {
    Ok(Value::new(context.session.session_values()))
  }
}

impl CompoundNode<NodeKey> for SessionValues {
  type Item = Value;
}

impl From<SessionValues> for NodeKey {
  fn from(n: SessionValues) -> Self {
    NodeKey::SessionValues(n)
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct RunId;

impl RunId {
  async fn run_node(self, context: Context) -> NodeResult<Value> {
    Ok(Python::with_gil(|py| {
      externs::unsafe_call(
        py,
        context.core.types.run_id,
        &[externs::store_u64(py, context.session.run_id().0 as u64)],
      )
    }))
  }
}

impl CompoundNode<NodeKey> for RunId {
  type Item = Value;
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
    let globs: Vec<String> = externs::getattr(item, "globs")
      .map_err(|e| format!("Failed to get `globs` for field: {e}"))?;

    let description_of_origin = externs::getattr_as_optional_string(item, "description_of_origin")
      .map_err(|e| format!("Failed to get `description_of_origin` for field: {e}"))?;

    let glob_match_error_behavior = externs::getattr(item, "glob_match_error_behavior")
      .map_err(|e| format!("Failed to get `glob_match_error_behavior` for field: {e}"))?;

    let failure_behavior: String = externs::getattr(glob_match_error_behavior, "value")
      .map_err(|e| format!("Failed to get `value` for field: {e}"))?;

    let strict_glob_matching =
      StrictGlobMatching::create(failure_behavior.as_str(), description_of_origin)?;

    let conjunction_obj = externs::getattr(item, "conjunction")
      .map_err(|e| format!("Failed to get `conjunction` for field: {e}"))?;

    let conjunction_string: String = externs::getattr(conjunction_obj, "value")
      .map_err(|e| format!("Failed to get `value` for field: {e}"))?;

    let conjunction = GlobExpansionConjunction::create(&conjunction_string)?;
    Ok(PathGlobs::new(globs, strict_glob_matching, conjunction))
  }

  pub fn lift_prepared_path_globs(item: &PyAny) -> Result<PreparedPathGlobs, String> {
    let path_globs = Snapshot::lift_path_globs(item)?;
    path_globs
      .parse()
      .map_err(|e| format!("Failed to parse PathGlobs for globs({item:?}): {e}"))
  }

  pub fn store_directory_digest(py: Python, item: DirectoryDigest) -> Result<Value, String> {
    let py_digest = Py::new(py, externs::fs::PyDigest(item)).map_err(|e| format!("{e}"))?;
    Ok(Value::new(py_digest.into_py(py)))
  }

  pub fn store_file_digest(py: Python, item: hashing::Digest) -> Result<Value, String> {
    let py_file_digest =
      Py::new(py, externs::fs::PyFileDigest(item)).map_err(|e| format!("{e}"))?;
    Ok(Value::new(py_file_digest.into_py(py)))
  }

  pub fn store_snapshot(py: Python, item: store::Snapshot) -> Result<Value, String> {
    let py_snapshot = Py::new(py, externs::fs::PySnapshot(item)).map_err(|e| format!("{e}"))?;
    Ok(Value::new(py_snapshot.into_py(py)))
  }

  pub fn store_path(py: Python, item: &Path) -> Result<Value, String> {
    if let Some(p) = item.as_os_str().to_str() {
      Ok(externs::store_utf8(py, p))
    } else {
      Err(format!("Could not decode path `{item:?}` as UTF8."))
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

  fn store_symlink_entry(
    py: Python,
    types: &crate::types::Types,
    item: &SymlinkEntry,
  ) -> Result<Value, String> {
    Ok(externs::unsafe_call(
      py,
      types.symlink_entry,
      &[
        Self::store_path(py, &item.path)?,
        externs::store_utf8(py, item.target.to_str().unwrap()),
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
        DigestEntry::Symlink(symlink_entry) => {
          Self::store_symlink_entry(py, &context.core.types, symlink_entry)
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

  async fn run_node(self, context: Context) -> NodeResult<store::Snapshot> {
    let path_globs = self.path_globs.parse().map_err(throw)?;

    // We rely on Context::expand_globs to track dependencies for scandirs,
    // and `context.get(DigestFile)` to track dependencies for file digests.
    let path_stats = context
      .expand_globs(
        path_globs,
        SymlinkBehavior::Oblivious,
        unmatched_globs_additional_context(),
      )
      .await?;

    store::Snapshot::from_path_stats(context.clone(), path_stats)
      .map_err(|e| throw(format!("Snapshot failed: {e}")))
      .await
  }
}

impl CompoundNode<NodeKey> for Snapshot {
  type Item = store::Snapshot;
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
    auth_headers: BTreeMap<String, String>,
    digest: hashing::Digest,
  ) -> Result<store::Snapshot, String> {
    let file_name = url
      .path_segments()
      .and_then(Iterator::last)
      .map(str::to_owned)
      .ok_or_else(|| format!("Error getting the file name from the parsed URL: {url}"))?;
    let path = RelativePath::new(&file_name).map_err(|e| {
      format!(
        "The file name derived from {} was {} which is not relative: {:?}",
        &url, &file_name, e
      )
    })?;

    // See if we have observed this URL and Digest before: if so, see whether we already have the
    // Digest fetched. The extra layer of indirection through the PersistentCache is to sanity
    // check that a Digest has ever been observed at the given URL.
    // NB: The auth_headers are not part of the key.
    let url_key = Self::url_key(&url, digest);
    let have_observed_url = core.local_cache.load(&url_key).await?.is_some();

    // If we hit the ObservedUrls cache, then we have successfully fetched this Digest from
    // this URL before. If we still have the bytes, then we skip fetching the content again.
    let usable_in_store = have_observed_url
      && (core
        .store()
        .load_file_bytes_with(digest, |_| ())
        .await
        .is_ok());

    if !usable_in_store {
      downloads::download(core.clone(), url, auth_headers, file_name, digest).await?;
      // The value was successfully fetched and matched the digest: record in the ObservedUrls
      // cache.
      core.local_cache.store(&url_key, Bytes::from("")).await?;
    }
    core.store().snapshot_of_one_file(path, digest, true).await
  }

  async fn run_node(self, context: Context) -> NodeResult<store::Snapshot> {
    let (url_str, expected_digest, auth_headers) = Python::with_gil(|py| {
      let py_download_file_val = self.0.to_value();
      let py_download_file = (*py_download_file_val).as_ref(py);
      let url_str: String = externs::getattr(py_download_file, "url")
        .map_err(|e| format!("Failed to get `url` for field: {e}"))?;
      let auth_headers = externs::getattr_from_str_frozendict(py_download_file, "auth_headers");
      let py_file_digest: PyFileDigest = externs::getattr(py_download_file, "expected_digest")?;
      let res: NodeResult<(String, Digest, BTreeMap<String, String>)> =
        Ok((url_str, py_file_digest.0, auth_headers));
      res
    })?;
    let url =
      Url::parse(&url_str).map_err(|err| throw(format!("Error parsing URL {url_str}: {err}")))?;
    self
      .load_or_download(context.core.clone(), url, auth_headers, expected_digest)
      .await
      .map_err(throw)
  }
}

impl CompoundNode<NodeKey> for DownloadedFile {
  type Item = store::Snapshot;
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
  // Handles the case where a generator requests a `Call` to a known `@rule`.
  async fn gen_call(
    context: &Context,
    mut params: Params,
    entry: Intern<rule_graph::Entry<Rule>>,
    call: externs::Call,
  ) -> NodeResult<Value> {
    let context = context.clone();
    let dependency_key = DependencyKey::for_known_rule(call.rule_id.clone(), call.output_type)
      .provided_params(call.inputs.iter().map(|t| *t.type_id()));
    params.extend(call.inputs.iter().cloned());

    let edges = context
      .core
      .rule_graph
      .edges_for_inner(&entry)
      .ok_or_else(|| throw(format!("No edges for task {entry:?} exist!")))?;

    // Find the entry for the Call.
    let select = edges
      .entry_for(&dependency_key)
      .map(|entry| {
        // The params for the Call replace existing params of the same type.
        Select::new(params.clone(), call.output_type, entry)
      })
      .ok_or_else(|| {
        // NB: The Python constructor for `Call()` will have already errored if
        // `type(input) != input_type`.
        throw(format!(
          "{call} was not detected in your @rule body at rule compile time."
        ))
      })?;
    select.run_node(context).await
  }

  // Handles the case where a generator produces a `Get` for an unknown `@rule`.
  async fn gen_get(
    context: &Context,
    mut params: Params,
    entry: Intern<rule_graph::Entry<Rule>>,
    get: externs::Get,
  ) -> NodeResult<Value> {
    let dependency_key =
      DependencyKey::new(get.output).provided_params(get.inputs.iter().map(|t| *t.type_id()));
    params.extend(get.inputs.iter().cloned());

    let edges = context
      .core
      .rule_graph
      .edges_for_inner(&entry)
      .ok_or_else(|| throw(format!("No edges for task {entry:?} exist!")))?;

    // Find the entry for the Get.
    let select = edges
      .entry_for(&dependency_key)
      .map(|entry| {
        // The subject of the Get is a new parameter that replaces an existing param of the same
        // type.
        Select::new(params.clone(), get.output, entry)
      })
      .or_else(|| {
        // The Get might have involved a @union: if so, include its in_scope types in the
        // lookup.
        let in_scope_types = get
          .input_types
          .iter()
          .find_map(|t| t.union_in_scope_types())?;
        edges
          .entry_for(
            &DependencyKey::new(get.output)
              .provided_params(get.inputs.iter().map(|k| *k.type_id()))
              .in_scope_params(in_scope_types),
          )
          .map(|entry| Select::new(params.clone(), get.output, entry))
      })
      .ok_or_else(|| {
        if get.input_types.iter().any(|t| t.is_union()) {
          throw(format!(
            "Invalid Get. Because an input type for `{get}` was annotated with `@union`, \
             the value for that type should be a member of that union. Did you \
             intend to register a `UnionRule`? If not, you may be using the incorrect \
             explicitly declared type.",
          ))
        } else {
          // NB: The Python constructor for `Get()` will have already errored if
          // `type(input) != input_type`.
          throw(format!(
            "{get} was not detected in your @rule body at rule compile time. \
             Was the `Get` constructor called in a non async-function, or \
             was it inside an async function defined after the @rule? \
             Make sure the `Get` is defined before or inside the @rule body.",
          ))
        }
      })?;
    select.run_node(context.clone()).await
  }

  // Handles the case where a generator produces either a `Get` or a generator.
  fn gen_get_or_generator(
    context: &Context,
    params: Params,
    entry: Intern<rule_graph::Entry<Rule>>,
    gog: externs::GetOrGenerator,
  ) -> BoxFuture<NodeResult<Value>> {
    async move {
      match gog {
        externs::GetOrGenerator::Get(get) => Self::gen_get(context, params, entry, get).await,
        externs::GetOrGenerator::Generator(generator) => {
          // TODO: The generator may run concurrently with any other generators requested in an
          // `All`/`MultiGet` (due to `future::try_join_all`), and so it needs its own workunit.
          // Should look into removing this constraint: possibly by running all generators from an
          // `All` on a tokio `LocalSet`.
          in_workunit!("generator", Level::Trace, |workunit| async move {
            let (value, _type_id) =
              Self::generate(context, workunit, params, entry, generator).await?;
            Ok(value)
          })
          .await
        }
      }
    }
    .boxed()
  }

  ///
  /// Given a python generator Value, loop to request the generator's dependencies until
  /// it completes with a result Value or fails with an error.
  ///
  async fn generate(
    context: &Context,
    workunit: &mut RunningWorkunit,
    params: Params,
    entry: Intern<rule_graph::Entry<Rule>>,
    generator: Value,
  ) -> NodeResult<(Value, TypeId)> {
    let mut input = GeneratorInput::Initial;
    loop {
      let response = Python::with_gil(|py| {
        externs::generator_send(py, &context.core.types.coroutine, &generator, input)
      })?;
      match response {
        GeneratorResponse::Call(call) => {
          let _blocking_token = workunit.blocking();
          let result = Self::gen_call(context, params.clone(), entry, call).await;
          match result {
            Ok(value) => {
              input = GeneratorInput::Arg(value);
            }
            Err(throw @ Failure::Throw { .. }) => {
              input = GeneratorInput::Err(PyErr::from(throw));
            }
            Err(failure) => break Err(failure),
          }
        }
        GeneratorResponse::Get(get) => {
          let _blocking_token = workunit.blocking();
          let result = Self::gen_get(context, params.clone(), entry, get).await;
          match result {
            Ok(value) => {
              input = GeneratorInput::Arg(value);
            }
            Err(throw @ Failure::Throw { .. }) => {
              input = GeneratorInput::Err(PyErr::from(throw));
            }
            Err(failure) => break Err(failure),
          }
        }
        GeneratorResponse::All(gogs) => {
          let _blocking_token = workunit.blocking();
          let get_futures = gogs
            .into_iter()
            .map(|gog| Self::gen_get_or_generator(context, params.clone(), entry, gog))
            .collect::<Vec<_>>();
          match future::try_join_all(get_futures).await {
            Ok(values) => {
              input = GeneratorInput::Arg(Python::with_gil(|py| externs::store_tuple(py, values)));
            }
            Err(throw @ Failure::Throw { .. }) => {
              input = GeneratorInput::Err(PyErr::from(throw));
            }
            Err(failure) => break Err(failure),
          }
        }
        GeneratorResponse::Break(val, type_id) => {
          break Ok((val, type_id));
        }
      }
    }
  }

  async fn run_node(self, context: Context, workunit: &mut RunningWorkunit) -> NodeResult<Value> {
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
          .args
          .iter()
          .map(|dependency_key| {
            Select::new_from_edges(params.clone(), dependency_key, edges).run_node(context.clone())
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
            .map_err(Failure::from)
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
      return Err(
        externs::IncorrectProductError::new_err(format!(
          "{:?} returned a result value that did not satisfy its constraints: {:?}",
          self.task.func, result_val
        ))
        .into(),
      );
    }

    if self.task.engine_aware_return_type {
      Python::with_gil(|py| {
        EngineAwareReturnType::update_workunit(workunit, (*result_val).as_ref(py))
      })
    };

    Ok(result_val)
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

impl CompoundNode<NodeKey> for Task {
  type Item = Value;
}

impl From<Task> for NodeKey {
  fn from(n: Task) -> Self {
    NodeKey::Task(Box::new(n))
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
  SessionValues(SessionValues),
  RunId(RunId),
  Task(Box<Task>),
}

impl NodeKey {
  pub fn fs_subject(&self) -> Option<&Path> {
    match self {
      NodeKey::DigestFile(s) => Some(s.0.path.as_path()),
      NodeKey::ReadLink(s) => Some((s.0).path.as_path()),
      NodeKey::Scandir(s) => Some((s.0).0.as_path()),

      // Not FS operations:
      // Explicitly listed so that if people add new NodeKeys they need to consider whether their
      // NodeKey represents an FS operation, and accordingly whether they need to add it to the
      // above list or the below list.
      &NodeKey::ExecuteProcess { .. }
      | &NodeKey::Select { .. }
      | &NodeKey::SessionValues { .. }
      | &NodeKey::RunId { .. }
      | &NodeKey::Snapshot { .. }
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
  fn workunit_desc(&self, context: &Context) -> Option<String> {
    match self {
      NodeKey::Task(ref task) => {
        let task_desc = task.task.display_info.desc.as_ref().map(|s| s.to_owned())?;

        let displayable_param_names: Vec<_> = Python::with_gil(|py| {
          Self::engine_aware_params(context, py, &task.params)
            .filter_map(|k| EngineAwareParameter::debug_hint((*k.value).as_ref(py)))
            .collect()
        });

        let desc = if displayable_param_names.is_empty() {
          task_desc
        } else {
          format!(
            "{} - {}",
            task_desc,
            display_sorted_in_parens(displayable_param_names.iter())
          )
        };

        Some(desc)
      }
      NodeKey::Snapshot(ref s) => Some(format!("Snapshotting: {}", s.path_globs)),
      NodeKey::ExecuteProcess(epr) => {
        // NB: See Self::workunit_level for more information on why this is prefixed.
        Some(format!("Scheduling: {}", epr.process.description))
      }
      NodeKey::DigestFile(DigestFile(File { path, .. })) => {
        Some(format!("Fingerprinting: {}", path.display()))
      }
      NodeKey::ReadLink(ReadLink(Link { path, .. })) => {
        Some(format!("Reading link: {}", path.display()))
      }
      NodeKey::Scandir(Scandir(Dir(path))) => {
        Some(format!("Reading directory: {}", path.display()))
      }
      NodeKey::DownloadedFile(..)
      | NodeKey::Select(..)
      | NodeKey::SessionValues(..)
      | NodeKey::RunId(..) => None,
    }
  }

  async fn maybe_watch(&self, context: &Context) -> NodeResult<()> {
    if let Some((path, watcher)) = self.fs_subject().zip(context.core.watcher.as_ref()) {
      let abs_path = context.core.build_root.join(path);
      watcher
        .watch(abs_path)
        .map_err(|e| Context::mk_error(&e))
        .await
    } else {
      Ok(())
    }
  }

  ///
  /// Filters the given Params to those which are subtypes of EngineAwareParameter.
  ///
  fn engine_aware_params<'a>(
    context: &Context,
    py: Python<'a>,
    params: &'a Params,
  ) -> impl Iterator<Item = &'a Key> + 'a {
    let engine_aware_param_ty = context.core.types.engine_aware_parameter.as_py_type(py);
    params.keys().filter(move |key| {
      key
        .type_id()
        .as_py_type(py)
        .is_subclass(engine_aware_param_ty)
        .unwrap_or(false)
    })
  }
}

#[async_trait]
impl Node for NodeKey {
  type Context = SessionCore;

  type Item = NodeOutput;
  type Error = Failure;

  async fn run(self, context: Context) -> Result<NodeOutput, Failure> {
    let workunit_name = self.workunit_name();
    let workunit_desc = self.workunit_desc(&context);
    let maybe_params = match &self {
      NodeKey::Task(ref task) => Some(&task.params),
      _ => None,
    };
    let context2 = context.clone();

    in_workunit!(
      workunit_name,
      self.workunit_level(),
      desc = workunit_desc.clone(),
      user_metadata = {
        if let Some(params) = maybe_params {
          Python::with_gil(|py| {
            Self::engine_aware_params(&context, py, params)
              .flat_map(|k| EngineAwareParameter::metadata((*k.value).as_ref(py)))
              .collect()
          })
        } else {
          vec![]
        }
      },
      |workunit| async move {
        // Ensure that we have installed filesystem watches before Nodes which inspect the
        // filesystem.
        let maybe_watch = self.maybe_watch(&context).await;

        let mut result = match self {
          NodeKey::DigestFile(n) => n.run_node(context).await.map(NodeOutput::FileDigest),
          NodeKey::DownloadedFile(n) => n.run_node(context).await.map(NodeOutput::Snapshot),
          NodeKey::ExecuteProcess(n) => {
            let backtrack_level = context.maybe_start_backtracking(&n);
            n.run_node(context, workunit, backtrack_level)
              .await
              .map(|r| NodeOutput::ProcessResult(Box::new(r)))
          }
          NodeKey::ReadLink(n) => n.run_node(context).await.map(NodeOutput::LinkDest),
          NodeKey::Scandir(n) => n.run_node(context).await.map(NodeOutput::DirectoryListing),
          NodeKey::Select(n) => n.run_node(context).await.map(NodeOutput::Value),
          NodeKey::Snapshot(n) => n.run_node(context).await.map(NodeOutput::Snapshot),
          NodeKey::SessionValues(n) => n.run_node(context).await.map(NodeOutput::Value),
          NodeKey::RunId(n) => n.run_node(context).await.map(NodeOutput::Value),
          NodeKey::Task(n) => n.run_node(context, workunit).await.map(NodeOutput::Value),
        };

        // If the Node failed with MissingDigest, attempt to invalidate the source of the Digest.
        result = context2.maybe_backtrack(&context2, result, workunit);

        // If both the Node and the watch failed, prefer the Node's error message (we have little
        // control over the error messages of the watch API).
        match (&result, maybe_watch) {
          (Ok(_), Ok(_)) => {}
          (Err(_), _) => {}
          (Ok(_), Err(e)) => {
            result = Err(e);
          }
        }

        // If the node failed, expand the Failure with a new frame.
        result = result.map_err(|failure| failure.with_pushed_frame(workunit_name, workunit_desc));

        result
      }
    )
    .await
  }

  fn restartable(&self) -> bool {
    // A Task / @rule is only restartable if it has not had a side effect (as determined by the
    // calls to the `task_side_effected` function).
    match self {
      NodeKey::Task(s) => !s.side_effected.load(Ordering::SeqCst),
      _ => true,
    }
  }

  fn cacheable(&self) -> bool {
    match self {
      NodeKey::Task(s) => s.task.cacheable,
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
            process_result.result.exit_code == 0
          }
          ProcessCacheScope::PerSession => false,
        }
      }
      (NodeKey::Task(ref t), NodeOutput::Value(ref v)) if t.task.engine_aware_return_type => {
        Python::with_gil(|py| EngineAwareReturnType::is_cacheable((**v).as_ref(py)).unwrap_or(true))
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
    let url =
      Python::with_gil(|py| externs::doc_url(py, "targets#dependencies-and-dependency-inference"));
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
      NodeKey::DigestFile(s) => write!(f, "DigestFile({})", s.0.path.display()),
      NodeKey::DownloadedFile(s) => write!(f, "DownloadedFile({})", s.0),
      NodeKey::ExecuteProcess(s) => {
        write!(f, "Process({})", s.process.description)
      }
      NodeKey::ReadLink(s) => write!(f, "ReadLink({})", (s.0).path.display()),
      NodeKey::Scandir(s) => write!(f, "Scandir({})", (s.0).0.display()),
      NodeKey::Select(s) => write!(f, "{}", s.product),
      NodeKey::Task(task) => {
        let params = {
          Python::with_gil(|py| {
            task
              .params
              .keys()
              .filter_map(|k| {
                EngineAwareParameter::debug_hint(k.to_value().clone_ref(py).into_ref(py))
              })
              .collect::<Vec<_>>()
          })
        };
        write!(
          f,
          "@rule({}({}))",
          task.task.display_info.name,
          params.join(", ")
        )
      }
      NodeKey::Snapshot(s) => write!(f, "Snapshot({})", s.path_globs),
      &NodeKey::SessionValues(_) => write!(f, "SessionValues"),
      &NodeKey::RunId(_) => write!(f, "RunId"),
    }
  }
}

impl NodeError for Failure {
  fn invalidated() -> Failure {
    Failure::Invalidated
  }

  fn generic(message: String) -> Failure {
    throw(message)
  }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub enum NodeOutput {
  FileDigest(hashing::Digest),
  Snapshot(store::Snapshot),
  DirectoryListing(Arc<DirectoryListing>),
  LinkDest(LinkDest),
  ProcessResult(Box<ProcessResult>),
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
        let mut digests = p.result.output_directory.digests();
        digests.push(p.result.stdout_digest);
        digests.push(p.result.stderr_digest);
        digests
      }
      NodeOutput::DirectoryListing(_) | NodeOutput::LinkDest(_) | NodeOutput::Value(_) => vec![],
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
