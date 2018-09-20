// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use futures::future::{self, Future};

use boxfuture::{BoxFuture, Boxable};
use context::{Context, Core};
use core::{throw, Failure, Key, Params, TypeConstraint, Value};
use externs;
use fs::{
  self, Dir, DirectoryListing, File, FileContent, GlobExpansionConjunction, GlobMatching, Link,
  PathGlobs, PathStat, StoreFileByDigest, StrictGlobMatching, VFS,
};
use hashing;
use process_execution::{self, CommandRunner};
use rule_graph;
use selectors;
use tasks::{self, Intrinsic, IntrinsicKind};

use graph::{Entry, Node, NodeError, NodeTracer, NodeVisualizer};

pub type NodeFuture<T> = BoxFuture<T, Failure>;

fn ok<O: Send + 'static>(value: O) -> NodeFuture<O> {
  future::ok(value).to_boxed()
}

fn err<O: Send + 'static>(failure: Failure) -> NodeFuture<O> {
  future::err(failure).to_boxed()
}

impl VFS<Failure> for Context {
  fn read_link(&self, link: &Link) -> NodeFuture<PathBuf> {
    self.get(ReadLink(link.clone())).map(|res| res.0).to_boxed()
  }

  fn scandir(&self, dir: Dir) -> NodeFuture<Arc<DirectoryListing>> {
    self.get(Scandir(dir))
  }

  fn is_ignored(&self, stat: &fs::Stat) -> bool {
    self.core.vfs.is_ignored(stat)
  }

  fn mk_error(msg: &str) -> Failure {
    Failure::Throw(
      externs::create_exception(msg),
      "<pants native internals>".to_string(),
    )
  }
}

impl StoreFileByDigest<Failure> for Context {
  fn store_by_digest(&self, file: File) -> BoxFuture<hashing::Digest, Failure> {
    self.get(DigestFile(file.clone()))
  }
}

///
/// A simplified implementation of graph::Node for members of the NodeKey enum to implement.
/// NodeKey's impl of graph::Node handles the rest.
///
/// The Item type of a WrappedNode is bounded to values that can be stored and retrieved
/// from the NodeResult enum. Due to the semantics of memoization, retrieving the typed result
/// stored inside the NodeResult requires an implementation of TryFrom<NodeResult>. But the
/// combination of bounds at usage sites should mean that a failure to unwrap the result is
/// exceedingly rare.
///
pub trait WrappedNode: Into<NodeKey> {
  type Item: TryFrom<NodeResult>;

  fn run(self, context: Context) -> BoxFuture<Self::Item, Failure>;
}

///
/// A Node that selects a product for some Params.
///
/// A Select can be satisfied by multiple sources, but fails if multiple sources produce a value.
/// The 'params' represent a series of type-keyed parameters that will be used by Nodes in the
/// subgraph below this Select.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub params: Params,
  pub selector: selectors::Select,
  entry: rule_graph::Entry,
}

impl Select {
  pub fn new(product: TypeConstraint, params: Params, edges: &rule_graph::RuleEdges) -> Select {
    Self::new_with_selector(selectors::Select::new(product), params, edges)
  }

  pub fn new_with_entries(
    product: TypeConstraint,
    params: Params,
    entry: rule_graph::Entry,
  ) -> Select {
    let selector = selectors::Select::new(product);
    Select {
      selector,
      params,
      entry,
    }
  }

  pub fn new_with_selector(
    selector: selectors::Select,
    params: Params,
    edges: &rule_graph::RuleEdges,
  ) -> Select {
    let select_key = rule_graph::SelectKey::JustSelect(selector.clone());
    // TODO: Is it worth propagating an error here?
    // TODO: Need to filter the parameters to what is actually used by this Entry.
    let entry = edges
      .entry_for(&select_key)
      .unwrap_or_else(|| panic!("{:?} did not declare a dependency on {:?}", edges, selector))
      .clone();
    Select {
      selector,
      params,
      entry,
    }
  }

  fn product(&self) -> &TypeConstraint {
    &self.selector.product
  }

  ///
  /// Looks for an is-a relationship between the given value and the requested product.
  ///
  /// Returns the original product Value for either success or failure.
  ///
  fn select_literal(&self, candidate: Value) -> Result<Value, Value> {
    if externs::satisfied_by(&self.selector.product, &candidate) {
      Ok(candidate)
    } else {
      Err(candidate)
    }
  }

  fn snapshot(
    &self,
    context: &Context,
    entry: &rule_graph::Entry,
  ) -> NodeFuture<Arc<fs::Snapshot>> {
    let edges = context
      .core
      .rule_graph
      .edges_for_inner(entry)
      .expect("Expected edges to exist for Snapshot intrinsic.");
    // Compute PathGlobs for the subject.
    let context = context.clone();
    Select::new(context.core.types.path_globs, self.params.clone(), &edges)
      .run(context.clone())
      .and_then(move |path_globs_val| context.get(Snapshot(externs::key_for(path_globs_val))))
      .to_boxed()
  }

  fn execute_process(
    &self,
    context: &Context,
    entry: &rule_graph::Entry,
  ) -> NodeFuture<ProcessResult> {
    let edges = &context
      .core
      .rule_graph
      .edges_for_inner(entry)
      .expect("Expected edges to exist for ExecuteProcess intrinsic.");
    // Compute an ExecuteProcessRequest for the subject.
    let context = context.clone();
    Select::new(
      context.core.types.process_request,
      self.params.clone(),
      edges,
    ).run(context.clone())
      .and_then(|process_request_val| {
        ExecuteProcess::lift(&process_request_val)
          .map_err(|str| throw(&format!("Error lifting ExecuteProcess: {}", str)))
      })
      .and_then(move |process_request| context.get(process_request))
      .to_boxed()
  }

  ///
  /// Return the Future for the Task that should compute the given product for the
  /// given Params.
  ///
  /// TODO: This could take `self` by value and avoid cloning.
  ///
  fn gen_node(&self, context: &Context) -> NodeFuture<Value> {
    if let Some(&(_, ref value)) = context.core.tasks.gen_singleton(self.product()) {
      return future::ok(value.clone()).to_boxed();
    }

    match &self.entry {
      &rule_graph::Entry::WithDeps(rule_graph::EntryWithDeps::Inner(ref inner)) => {
        match inner.rule() {
          &rule_graph::Rule::Task(ref task) => context.get(Task {
            params: self.params.clone(),
            product: *self.product(),
            task: task.clone(),
            entry: Arc::new(self.entry.clone()),
          }),
          &rule_graph::Rule::Intrinsic(Intrinsic {
            kind: IntrinsicKind::Snapshot,
            ..
          }) => {
            let context = context.clone();
            self
              .snapshot(&context, &self.entry)
              .map(move |snapshot| Snapshot::store_snapshot(&context.core, &snapshot))
              .to_boxed()
          }
          &rule_graph::Rule::Intrinsic(Intrinsic {
            kind: IntrinsicKind::FilesContent,
            ..
          }) => {
            let edges = &context
              .core
              .rule_graph
              .edges_for_inner(&self.entry)
              .expect("Expected edges to exist for FilesContent intrinsic.");
            let context = context.clone();
            Select::new(
              context.core.types.directory_digest,
              self.params.clone(),
              edges,
            ).run(context.clone())
              .and_then(|directory_digest_val| {
                lift_digest(&directory_digest_val).map_err(|str| throw(&str))
              })
              .and_then(move |digest| {
                let store = context.core.store.clone();
                context
                  .core
                  .store
                  .load_directory(digest)
                  .map_err(|str| throw(&str))
                  .and_then(move |maybe_directory| {
                    maybe_directory
                      .ok_or_else(|| format!("Could not find directory with digest {:?}", digest))
                      .map_err(|str| throw(&str))
                  })
                  .and_then(move |directory| {
                    store
                      .contents_for_directory(&directory)
                      .map_err(|str| throw(&str))
                  })
                  .map(move |files_content| Snapshot::store_files_content(&context, &files_content))
              })
              .to_boxed()
          }
          &rule_graph::Rule::Intrinsic(Intrinsic {
            kind: IntrinsicKind::ProcessExecution,
            ..
          }) => {
            let context = context.clone();
            self
              .execute_process(&context, &self.entry)
              .map(move |result| {
                externs::unsafe_call(
                  &context.core.types.construct_process_result,
                  &[
                    externs::store_bytes(&result.0.stdout),
                    externs::store_bytes(&result.0.stderr),
                    externs::store_i64(result.0.exit_code.into()),
                    Snapshot::store_directory(&context.core, &result.0.output_directory),
                  ],
                )
              })
              .to_boxed()
          }
        }
      }
      &rule_graph::Entry::WithDeps(rule_graph::EntryWithDeps::Root(_))
      | &rule_graph::Entry::Param(_)
      | &rule_graph::Entry::Singleton { .. } => {
        // TODO: gen_node should be inlined, and should use these Entry types to skip
        // any runtime checks of python objects.
        panic!("Not a runtime-executable entry! {:?}", self.entry)
      }
    }
  }
}

// TODO: This is a Node only because it is used as a root in the graph, but it should never be
// requested using context.get
impl WrappedNode for Select {
  type Item = Value;

  fn run(self, context: Context) -> NodeFuture<Value> {
    // If the Subject "is a" or "has a" Product, then we're done.
    if let Ok(value) = self.select_literal(externs::val_for(self.params.expect_single())) {
      return ok(value);
    }

    // Attempt to use the configured Task to compute the value.
    self
      .gen_node(&context)
      .and_then(move |value| {
        self.select_literal(value).map_err(|value| {
          throw(&format!(
            "{} returned a result value that did not satisfy its constraints: {:?}",
            rule_graph::entry_str(&self.entry),
            value
          ))
        })
      })
      .to_boxed()
  }
}

impl From<Select> for NodeKey {
  fn from(n: Select) -> Self {
    NodeKey::Select(n)
  }
}

pub fn lift_digest(digest: &Value) -> Result<hashing::Digest, String> {
  let fingerprint = externs::project_str(&digest, "fingerprint");
  let digest_length = externs::project_str(&digest, "serialized_bytes_length");
  let digest_length_as_usize = digest_length
    .parse::<usize>()
    .map_err(|err| format!("Length was not a usize: {:?}", err))?;
  Ok(hashing::Digest(
    hashing::Fingerprint::from_hex_string(&fingerprint)?,
    digest_length_as_usize,
  ))
}

///
/// A Node that represents executing a process.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ExecuteProcess(process_execution::ExecuteProcessRequest);

impl ExecuteProcess {
  ///
  /// Lifts a Key representing a python ExecuteProcessRequest value into a ExecuteProcess Node.
  ///
  fn lift(value: &Value) -> Result<ExecuteProcess, String> {
    let mut env: BTreeMap<String, String> = BTreeMap::new();
    let env_var_parts = externs::project_multi_strs(&value, "env");
    if env_var_parts.len() % 2 != 0 {
      return Err("Error parsing env: odd number of parts".to_owned());
    }
    for i in 0..(env_var_parts.len() / 2) {
      env.insert(
        env_var_parts[2 * i].clone(),
        env_var_parts[2 * i + 1].clone(),
      );
    }
    let digest = lift_digest(&externs::project_ignoring_type(&value, "input_files"))
      .map_err(|err| format!("Error parsing digest {}", err))?;

    let output_files = externs::project_multi_strs(&value, "output_files")
      .into_iter()
      .map(PathBuf::from)
      .collect();

    let output_directories = externs::project_multi_strs(&value, "output_directories")
      .into_iter()
      .map(PathBuf::from)
      .collect();

    let timeout_str = externs::project_str(&value, "timeout_seconds");
    let timeout_in_seconds = timeout_str
      .parse::<f64>()
      .map_err(|err| format!("Timeout was not a float: {:?}", err))?;

    if timeout_in_seconds < 0.0 {
      return Err(format!("Timeout was negative: {:?}", timeout_in_seconds));
    }

    let description = externs::project_str(&value, "description");

    let jdk_home = {
      let val = externs::project_str(&value, "jdk_home");
      if val.is_empty() {
        None
      } else {
        Some(PathBuf::from(val))
      }
    };

    Ok(ExecuteProcess(process_execution::ExecuteProcessRequest {
      argv: externs::project_multi_strs(&value, "argv"),
      env: env,
      input_files: digest,
      output_files: output_files,
      output_directories: output_directories,
      timeout: Duration::from_millis((timeout_in_seconds * 1000.0) as u64),
      description: description,
      jdk_home: jdk_home,
    }))
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcessResult(process_execution::FallibleExecuteProcessResult);

impl WrappedNode for ExecuteProcess {
  type Item = ProcessResult;

  fn run(self, context: Context) -> NodeFuture<ProcessResult> {
    let request = self.0;

    context
      .core
      .command_runner
      .run(request)
      .map(ProcessResult)
      .map_err(|e| throw(&format!("Failed to execute process: {}", e)))
      .to_boxed()
  }
}

impl From<ExecuteProcess> for NodeKey {
  fn from(n: ExecuteProcess) -> Self {
    NodeKey::ExecuteProcess(n)
  }
}

///
/// A Node that represents reading the destination of a symlink (non-recursively).
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ReadLink(Link);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LinkDest(PathBuf);

impl WrappedNode for ReadLink {
  type Item = LinkDest;

  fn run(self, context: Context) -> NodeFuture<LinkDest> {
    let link = self.0.clone();
    context
      .core
      .vfs
      .read_link(&self.0)
      .map(LinkDest)
      .map_err(move |e| throw(&format!("Failed to read_link for {:?}: {:?}", link, e)))
      .to_boxed()
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

impl WrappedNode for DigestFile {
  type Item = hashing::Digest;

  fn run(self, context: Context) -> NodeFuture<hashing::Digest> {
    let file = self.0.clone();
    context
      .core
      .vfs
      .read_file(&self.0)
      .map_err(move |e| throw(&format!("Error reading file {:?}: {:?}", file, e,)))
      .and_then(move |c| {
        context
          .core
          .store
          .store_file_bytes(c.content, true)
          .map_err(|e| throw(&e))
      })
      .to_boxed()
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

impl WrappedNode for Scandir {
  type Item = Arc<DirectoryListing>;

  fn run(self, context: Context) -> NodeFuture<Arc<DirectoryListing>> {
    let dir = self.0.clone();
    context
      .core
      .vfs
      .scandir(&self.0)
      .then(move |listing_res| match listing_res {
        Ok(listing) => Ok(Arc::new(listing)),
        Err(e) => Err(throw(&format!("Failed to scandir for {:?}: {:?}", dir, e))),
      })
      .to_boxed()
  }
}

impl From<Scandir> for NodeKey {
  fn from(n: Scandir) -> Self {
    NodeKey::Scandir(n)
  }
}

///
/// A Node that captures an fs::Snapshot for a PathGlobs subject.
///
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Snapshot(Key);

impl Snapshot {
  fn create(context: Context, path_globs: PathGlobs) -> NodeFuture<fs::Snapshot> {
    // Recursively expand PathGlobs into PathStats.
    // We rely on Context::expand tracking dependencies for scandirs,
    // and fs::Snapshot::from_path_stats tracking dependencies for file digests.
    context
      .expand(path_globs)
      .map_err(|e| format!("PathGlobs expansion failed: {:?}", e))
      .and_then(move |path_stats| {
        fs::Snapshot::from_path_stats(context.core.store.clone(), &context, path_stats)
          .map_err(move |e| format!("Snapshot failed: {}", e))
      })
      .map_err(|e| throw(&e))
      .to_boxed()
  }

  pub fn lift_path_globs(item: &Value) -> Result<PathGlobs, String> {
    let include = externs::project_multi_strs(item, "include");
    let exclude = externs::project_multi_strs(item, "exclude");

    let glob_match_error_behavior =
      externs::project_ignoring_type(item, "glob_match_error_behavior");
    let failure_behavior = externs::project_str(&glob_match_error_behavior, "failure_behavior");
    let strict_glob_matching = StrictGlobMatching::create(failure_behavior.as_str())?;

    let conjunction_obj = externs::project_ignoring_type(item, "conjunction");
    let conjunction_string = externs::project_str(&conjunction_obj, "conjunction");
    let conjunction = GlobExpansionConjunction::create(&conjunction_string)?;

    PathGlobs::create(&include, &exclude, strict_glob_matching, conjunction).map_err(|e| {
      format!(
        "Failed to parse PathGlobs for include({:?}), exclude({:?}): {}",
        include, exclude, e
      )
    })
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

  pub fn store_snapshot(core: &Arc<Core>, item: &fs::Snapshot) -> Value {
    let path_stats: Vec<_> = item
      .path_stats
      .iter()
      .map(|ps| Self::store_path_stat(core, ps))
      .collect();
    externs::unsafe_call(
      &core.types.construct_snapshot,
      &[
        Self::store_directory(core, &item.digest),
        externs::store_tuple(&path_stats),
      ],
    )
  }

  fn store_path(item: &Path) -> Value {
    externs::store_utf8_osstr(item.as_os_str())
  }

  fn store_dir(core: &Arc<Core>, item: &Dir) -> Value {
    let args = [Self::store_path(item.0.as_path())];
    externs::unsafe_call(&core.types.construct_dir, &args)
  }

  fn store_file(core: &Arc<Core>, item: &File) -> Value {
    let args = [Self::store_path(item.path.as_path())];
    externs::unsafe_call(&core.types.construct_file, &args)
  }

  fn store_path_stat(core: &Arc<Core>, item: &PathStat) -> Value {
    let args = match item {
      &PathStat::Dir { ref path, ref stat } => {
        vec![Self::store_path(path), Self::store_dir(core, stat)]
      }
      &PathStat::File { ref path, ref stat } => {
        vec![Self::store_path(path), Self::store_file(core, stat)]
      }
    };
    externs::unsafe_call(&core.types.construct_path_stat, &args)
  }

  fn store_file_content(context: &Context, item: &FileContent) -> Value {
    externs::unsafe_call(
      &context.core.types.construct_file_content,
      &[
        Self::store_path(&item.path),
        externs::store_bytes(&item.content),
      ],
    )
  }

  fn store_files_content(context: &Context, item: &[FileContent]) -> Value {
    let entries: Vec<_> = item
      .iter()
      .map(|e| Self::store_file_content(context, e))
      .collect();
    externs::unsafe_call(
      &context.core.types.construct_files_content,
      &[externs::store_tuple(&entries)],
    )
  }
}

impl WrappedNode for Snapshot {
  type Item = Arc<fs::Snapshot>;

  fn run(self, context: Context) -> NodeFuture<Arc<fs::Snapshot>> {
    let lifted_path_globs = Self::lift_path_globs(&externs::val_for(&self.0));
    future::result(lifted_path_globs)
      .map_err(|e| throw(&format!("Failed to parse PathGlobs: {}", e)))
      .and_then(move |path_globs| Self::create(context, path_globs))
      .map(Arc::new)
      .to_boxed()
  }
}

impl From<Snapshot> for NodeKey {
  fn from(n: Snapshot) -> Self {
    NodeKey::Snapshot(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  params: Params,
  product: TypeConstraint,
  task: tasks::Task,
  entry: Arc<rule_graph::Entry>,
}

impl Task {
  fn gen_get(
    context: &Context,
    entry: &Arc<rule_graph::Entry>,
    gets: Vec<externs::Get>,
  ) -> NodeFuture<Vec<Value>> {
    let get_futures = gets
      .into_iter()
      .map(|externs::Get(product, subject)| {
        // TODO: The subject of the get is a new parameter, but params from the context should be
        // included as well. Additionally, params should be filtered to what is used by the Entry.
        //   see https://github.com/pantsbuild/pants/issues/6478
        let params = Params::new_single(subject);
        let select_key = rule_graph::SelectKey::JustGet(selectors::Get {
          product: product,
          subject: *subject.type_id(),
        });
        let entry = context
          .core
          .rule_graph
          .edges_for_inner(entry)
          .expect("edges for task exist.")
          .entry_for(&select_key)
          .unwrap_or_else(|| {
            panic!(
              "{:?} did not declare a dependency on {:?}",
              entry, select_key
            )
          })
          .clone();
        Select::new_with_entries(product, params, entry).run(context.clone())
      })
      .collect::<Vec<_>>();
    future::join_all(get_futures).to_boxed()
  }

  ///
  /// Given a python generator Value, loop to request the generator's dependencies until
  /// it completes with a result Value.
  ///
  fn generate(
    context: Context,
    entry: Arc<rule_graph::Entry>,
    generator: Value,
  ) -> NodeFuture<Value> {
    future::loop_fn(externs::eval("None").unwrap(), move |input| {
      let context = context.clone();
      let entry = entry.clone();
      future::result(externs::generator_send(&generator, &input)).and_then(move |response| {
        match response {
          externs::GeneratorResponse::Get(get) => Self::gen_get(&context, &entry, vec![get])
            .map(|vs| future::Loop::Continue(vs.into_iter().next().unwrap()))
            .to_boxed(),
          externs::GeneratorResponse::GetMulti(gets) => Self::gen_get(&context, &entry, gets)
            .map(|vs| future::Loop::Continue(externs::store_tuple(&vs)))
            .to_boxed(),
          externs::GeneratorResponse::Break(val) => future::ok(future::Loop::Break(val)).to_boxed(),
        }
      })
    }).to_boxed()
  }
}

impl WrappedNode for Task {
  type Item = Value;

  fn run(self, context: Context) -> NodeFuture<Value> {
    let deps = {
      let edges = &context
        .core
        .rule_graph
        .edges_for_inner(&self.entry)
        .expect("edges for task exist.");
      let params = self.params;
      future::join_all(
        self
          .task
          .clause
          .into_iter()
          .map(|s| Select::new_with_selector(s, params.clone(), edges).run(context.clone()))
          .collect::<Vec<_>>(),
      )
    };

    let func = self.task.func;
    let entry = self.entry;
    deps
      .then(move |deps_result| match deps_result {
        Ok(deps) => externs::call(&externs::val_for(&func.0), &deps),
        Err(failure) => Err(failure),
      })
      .then(move |task_result| match task_result {
        Ok(val) => {
          if externs::satisfied_by(&context.core.types.generator, &val) {
            Self::generate(context, entry, val)
          } else {
            ok(val)
          }
        }
        Err(failure) => err(failure),
      })
      .to_boxed()
  }
}

impl From<Task> for NodeKey {
  fn from(n: Task) -> Self {
    NodeKey::Task(n)
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

  fn color(&mut self, entry: &Entry<NodeKey>) -> String {
    let max_colors = 12;
    match entry.peek() {
      None => "white".to_string(),
      Some(Err(Failure::Throw(..))) => "4".to_string(),
      Some(Err(Failure::Invalidated)) => "12".to_string(),
      Some(Ok(_)) => {
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

pub struct Tracer;

impl NodeTracer<NodeKey> for Tracer {
  fn is_bottom(result: Option<Result<NodeResult, Failure>>) -> bool {
    match result {
      Some(Err(Failure::Invalidated)) => false,
      Some(Err(Failure::Throw(..))) => false,
      Some(Ok(_)) => true,
      None => {
        // A Node with no state is either still running, or effectively cancelled
        // because a dependent failed. In either case, it's not useful to render
        // them, as we don't know whether they would have succeeded or failed.
        true
      }
    }
  }

  fn state_str(indent: &str, result: Option<Result<NodeResult, Failure>>) -> String {
    match result {
      None => "<None>".to_string(),
      Some(Ok(ref x)) => format!("{:?}", x),
      Some(Err(Failure::Throw(ref x, ref traceback))) => format!(
        "Throw({})\n{}",
        externs::val_to_str(x),
        traceback
          .split('\n')
          .map(|l| format!("{}    {}", indent, l))
          .collect::<Vec<_>>()
          .join("\n")
      ),
      Some(Err(Failure::Invalidated)) => "Invalidated".to_string(),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum NodeKey {
  DigestFile(DigestFile),
  ExecuteProcess(ExecuteProcess),
  ReadLink(ReadLink),
  Scandir(Scandir),
  Select(Select),
  Snapshot(Snapshot),
  Task(Task),
}

impl NodeKey {
  fn product_str(&self) -> String {
    fn typstr(tc: &TypeConstraint) -> String {
      externs::key_to_str(&tc.0)
    }
    match self {
      &NodeKey::ExecuteProcess(..) => "ProcessResult".to_string(),
      &NodeKey::Select(ref s) => typstr(&s.selector.product),
      &NodeKey::Task(ref s) => typstr(&s.product),
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
      &NodeKey::ExecuteProcess { .. }
      | &NodeKey::Select { .. }
      | &NodeKey::Snapshot { .. }
      | &NodeKey::Task { .. } => None,
    }
  }
}

impl Node for NodeKey {
  type Context = Context;

  type Item = NodeResult;
  type Error = Failure;

  fn run(self, context: Context) -> NodeFuture<NodeResult> {
    match self {
      NodeKey::DigestFile(n) => n.run(context).map(|v| v.into()).to_boxed(),
      NodeKey::ExecuteProcess(n) => n.run(context).map(|v| v.into()).to_boxed(),
      NodeKey::ReadLink(n) => n.run(context).map(|v| v.into()).to_boxed(),
      NodeKey::Scandir(n) => n.run(context).map(|v| v.into()).to_boxed(),
      NodeKey::Select(n) => n.run(context).map(|v| v.into()).to_boxed(),
      NodeKey::Snapshot(n) => n.run(context).map(|v| v.into()).to_boxed(),
      NodeKey::Task(n) => n.run(context).map(|v| v.into()).to_boxed(),
    }
  }

  fn format(&self) -> String {
    fn keystr(key: &Key) -> String {
      externs::key_to_str(&key)
    }
    fn typstr(tc: &TypeConstraint) -> String {
      externs::key_to_str(&tc.0)
    }
    // TODO: these should all be converted to fmt::Debug implementations, and then this method can
    // go away in favor of the auto-derived Debug for this type.
    match self {
      &NodeKey::DigestFile(ref s) => format!("DigestFile({:?})", s.0),
      &NodeKey::ExecuteProcess(ref s) => format!("ExecuteProcess({:?}", s.0),
      &NodeKey::ReadLink(ref s) => format!("ReadLink({:?})", s.0),
      &NodeKey::Scandir(ref s) => format!("Scandir({:?})", s.0),
      &NodeKey::Select(ref s) => format!(
        "Select({}, {})",
        keystr(&s.params.expect_single()),
        typstr(&s.selector.product)
      ),
      &NodeKey::Task(ref s) => format!(
        "Task({}, {}, {})",
        externs::project_str(&externs::val_for(&s.task.func.0), "__name__"),
        keystr(&s.params.expect_single()),
        typstr(&s.product)
      ),
      &NodeKey::Snapshot(ref s) => format!("Snapshot({})", keystr(&s.0)),
    }
  }

  fn digest(res: NodeResult) -> Option<hashing::Digest> {
    match res {
      NodeResult::Digest(d) => Some(d),
      NodeResult::DirectoryListing(_)
      | NodeResult::LinkDest(_)
      | NodeResult::ProcessResult(_)
      | NodeResult::Snapshot(_)
      | NodeResult::Value(_) => None,
    }
  }
}

impl NodeError for Failure {
  fn invalidated() -> Failure {
    Failure::Invalidated
  }

  fn cyclic() -> Failure {
    throw("Dep graph contained a cycle.")
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NodeResult {
  Digest(hashing::Digest),
  DirectoryListing(Arc<DirectoryListing>),
  LinkDest(LinkDest),
  ProcessResult(ProcessResult),
  Snapshot(Arc<fs::Snapshot>),
  Value(Value),
}

impl From<Value> for NodeResult {
  fn from(v: Value) -> Self {
    NodeResult::Value(v)
  }
}

impl From<Arc<fs::Snapshot>> for NodeResult {
  fn from(v: Arc<fs::Snapshot>) -> Self {
    NodeResult::Snapshot(v)
  }
}

impl From<hashing::Digest> for NodeResult {
  fn from(v: hashing::Digest) -> Self {
    NodeResult::Digest(v)
  }
}

impl From<ProcessResult> for NodeResult {
  fn from(v: ProcessResult) -> Self {
    NodeResult::ProcessResult(v)
  }
}

impl From<LinkDest> for NodeResult {
  fn from(v: LinkDest) -> Self {
    NodeResult::LinkDest(v)
  }
}

impl From<Arc<DirectoryListing>> for NodeResult {
  fn from(v: Arc<DirectoryListing>) -> Self {
    NodeResult::DirectoryListing(v)
  }
}

// TODO: These traits exist in the stdlib, but are marked unstable.
//   see https://github.com/rust-lang/rust/issues/33417
pub trait TryFrom<T>: Sized {
  type Err;
  fn try_from(t: T) -> Result<Self, Self::Err>;
}

pub trait TryInto<T>: Sized {
  type Err;
  fn try_into(self) -> Result<T, Self::Err>;
}

impl<T, U> TryInto<U> for T
where
  U: TryFrom<T>,
{
  type Err = U::Err;

  fn try_into(self) -> Result<U, U::Err> {
    U::try_from(self)
  }
}

impl TryFrom<NodeResult> for NodeResult {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    Ok(nr)
  }
}

impl TryFrom<NodeResult> for Value {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::Value(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeResult> for Arc<fs::Snapshot> {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::Snapshot(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeResult> for hashing::Digest {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::Digest(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeResult> for ProcessResult {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::ProcessResult(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeResult> for LinkDest {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::LinkDest(v) => Ok(v),
      _ => Err(()),
    }
  }
}

impl TryFrom<NodeResult> for Arc<DirectoryListing> {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::DirectoryListing(v) => Ok(v),
      _ => Err(()),
    }
  }
}
