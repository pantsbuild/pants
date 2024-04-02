// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::convert::TryFrom;
use std::fmt::Display;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use deepsize::DeepSizeOf;
use futures::future::{self, BoxFuture, FutureExt, TryFutureExt};
use internment::Intern;
use pyo3::prelude::{PyAny, Python};

use crate::context::{Context, SessionCore};
use crate::externs;
use crate::python::{display_sorted_in_parens, throw, Failure, Key, Params, TypeId, Value};
use crate::tasks::{self, Rule};
use fs::{self, Dir, DirectoryDigest, DirectoryListing, File, Link, Vfs};
use process_execution::{self, ProcessCacheScope};

use crate::externs::engine_aware::{EngineAwareParameter, EngineAwareReturnType};
use graph::{Node, NodeError};
use rule_graph::{DependencyKey, Query};
use store::{self, StoreFileByDigest};
use workunit_store::{in_workunit, Level};

// Sub-modules for the differnt node kinds.
mod digest_file;
mod downloaded_file;
mod execute_process;
mod read_link;
mod root;
mod run_id;
mod scandir;
mod session_values;
mod snapshot;
mod task;

// Re-export symbols for each kind of node.
pub use self::digest_file::DigestFile;
pub use self::downloaded_file::DownloadedFile;
pub use self::execute_process::{ExecuteProcess, ProcessResult};
pub use self::read_link::{LinkDest, ReadLink};
pub use self::root::Root;
pub use self::run_id::RunId;
pub use self::scandir::Scandir;
pub use self::session_values::SessionValues;
pub use self::snapshot::Snapshot;
pub use self::task::Task;

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

async fn select(
    context: Context,
    args: Option<Key>,
    args_arity: u16,
    mut params: Params,
    entry: Intern<rule_graph::Entry<Rule>>,
) -> NodeResult<Value> {
    params.retain(|k| match entry.as_ref() {
        rule_graph::Entry::Param(type_id) => type_id == k.type_id(),
        rule_graph::Entry::WithDeps(with_deps) => with_deps.params().contains(k.type_id()),
    });
    match entry.as_ref() {
        &rule_graph::Entry::WithDeps(wd) => match wd.as_ref() {
            rule_graph::EntryWithDeps::Rule(ref rule) => match rule.rule() {
                tasks::Rule::Task(task) => {
                    context
                        .get(Task {
                            params: params.clone(),
                            args,
                            args_arity,
                            task: *task,
                            entry: entry,
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
                                select_product(
                                    context.clone(),
                                    params.clone(),
                                    dependency_key,
                                    "intrinsic",
                                    entry,
                                )
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
                select_reentry(context, params, &reentry.query).await
            }
            &rule_graph::EntryWithDeps::Root(_) => {
                panic!("Not a runtime-executable entry! {:?}", entry)
            }
        },
        &rule_graph::Entry::Param(type_id) => {
            if let Some(key) = params.find(type_id) {
                Ok(key.to_value())
            } else {
                Err(throw(format!(
                    "Expected a Param of type {} to be present, but had only: {}",
                    type_id, params,
                )))
            }
        }
    }
}

fn select_reentry(
    context: Context,
    params: Params,
    query: &Query<TypeId>,
) -> BoxFuture<NodeResult<Value>> {
    // TODO: Actually using the `RuleEdges` of this entry to compute inputs is not
    // implemented: doing so would involve doing something similar to what we do for
    // intrinsics above, and waiting to compute inputs before executing the query here.
    //
    // That doesn't block using a singleton to provide an API type, but it would block a more
    // complex use case.
    //
    // see https://github.com/pantsbuild/pants/issues/16751
    let product = query.product;
    let edges = context
        .core
        .rule_graph
        .find_root(query.params.iter().cloned(), product)
        .map(|(_, edges)| edges);

    async move {
        let edges = edges?;
        let entry = edges
            .entry_for(&DependencyKey::new(product))
            .unwrap_or_else(|| panic!("{edges:?} did not declare a dependency on {product}"));
        select(context, None, 0, params, entry).await
    }
    .boxed()
}

fn select_product<'a>(
    context: Context,
    params: Params,
    dependency_key: &'a DependencyKey<TypeId>,
    caller_description: &'a str,
    entry: Intern<rule_graph::Entry<Rule>>,
) -> BoxFuture<'a, NodeResult<Value>> {
    let edges = context
        .core
        .rule_graph
        .edges_for_inner(&entry)
        .ok_or_else(|| {
            throw(format!(
                "Tried to request {dependency_key} for {caller_description} but found no edges"
            ))
        });
    async move {
        let edges = edges?;
        let entry = edges.entry_for(dependency_key).unwrap_or_else(|| {
            panic!("{caller_description} did not declare a dependency on {dependency_key:?}")
        });
        select(context, None, 0, params, entry).await
    }
    .boxed()
}

pub fn lift_directory_digest(digest: &PyAny) -> Result<DirectoryDigest, String> {
    let py_digest: externs::fs::PyDigest = digest.extract().map_err(|e| format!("{e}"))?;
    Ok(py_digest.0)
}

pub fn lift_file_digest(digest: &PyAny) -> Result<hashing::Digest, String> {
    let py_file_digest: externs::fs::PyFileDigest = digest.extract().map_err(|e| format!("{e}"))?;
    Ok(py_file_digest.0)
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
    Root(Box<Root>),
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
            | &NodeKey::Root { .. }
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
            NodeKey::Root(..) => "root",
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
            | NodeKey::Root(..)
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
            key.type_id()
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
                    NodeKey::DownloadedFile(n) => {
                        n.run_node(context).await.map(NodeOutput::Snapshot)
                    }
                    NodeKey::ExecuteProcess(n) => {
                        let backtrack_level = context.maybe_start_backtracking(&n);
                        n.run_node(context, workunit, backtrack_level)
                            .await
                            .map(|r| NodeOutput::ProcessResult(Box::new(r)))
                    }
                    NodeKey::ReadLink(n) => n.run_node(context).await.map(NodeOutput::LinkDest),
                    NodeKey::Scandir(n) => {
                        n.run_node(context).await.map(NodeOutput::DirectoryListing)
                    }
                    NodeKey::Root(n) => n.run_node(context).await.map(NodeOutput::Value),
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
                result = result
                    .map_err(|failure| failure.with_pushed_frame(workunit_name, workunit_desc));

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
                Python::with_gil(|py| {
                    EngineAwareReturnType::is_cacheable((**v).as_ref(py)).unwrap_or(true)
                })
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
        let url = Python::with_gil(|py| {
            externs::doc_url(py, "docs/using-pants/key-concepts/targets-and-build-files#dependencies-and-dependency-inference")
        });
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
            NodeKey::Root(s) => write!(f, "{}", s.product),
            NodeKey::Task(task) => {
                let params = {
                    Python::with_gil(|py| {
                        task.params
                            .keys()
                            .filter_map(|k| {
                                EngineAwareParameter::debug_hint(
                                    k.to_value().clone_ref(py).into_ref(py),
                                )
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
            NodeOutput::DirectoryListing(_) | NodeOutput::LinkDest(_) | NodeOutput::Value(_) => {
                vec![]
            }
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
