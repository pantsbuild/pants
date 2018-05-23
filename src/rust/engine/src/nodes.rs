// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

extern crate bazel_protos;
extern crate tempdir;

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use futures::future::{self, Future};

use boxfuture::{BoxFuture, Boxable};
use context::{Context, Core};
use core::{throw, Failure, Key, Noop, TypeConstraint, Value, Variants};
use externs;
use fs::{self, Dir, File, FileContent, Link, PathGlobs,
         PathStat, StrictGlobMatching, StoreFileByDigest, VFS};
use hashing;
use process_execution;
use rule_graph;
use selectors;
use tasks::{self, Intrinsic, IntrinsicKind};

pub type NodeFuture<T> = BoxFuture<T, Failure>;

fn ok<O: Send + 'static>(value: O) -> NodeFuture<O> {
  future::ok(value).to_boxed()
}

fn err<O: Send + 'static>(failure: Failure) -> NodeFuture<O> {
  future::err(failure).to_boxed()
}

///
/// A helper to indicate that the value represented by the Failure was required, and thus
/// fatal if not present.
///
fn was_required(failure: Failure) -> Failure {
  match failure {
    Failure::Noop(noop) => throw(&format!("No source of required dependency: {:?}", noop)),
    f => f,
  }
}

pub trait GetNode {
  fn get<N: Node>(&self, node: N) -> NodeFuture<N::Output>;
}

impl VFS<Failure> for Context {
  fn read_link(&self, link: Link) -> NodeFuture<PathBuf> {
    self.get(ReadLink(link)).map(|res| res.0).to_boxed()
  }

  fn scandir(&self, dir: Dir) -> NodeFuture<Vec<fs::Stat>> {
    self.get(Scandir(dir)).map(|res| res.0).to_boxed()
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
/// Defines executing a cacheable/memoizable step for the given context.
///
/// The Output type of a Node is bounded to values that can be stored and retrieved from
/// the NodeResult enum. Due to the semantics of memoization, retrieving the typed result
/// stored inside the NodeResult requires an implementation of TryFrom<NodeResult>. But the
/// combination of bounds at usage sites should mean that a failure to unwrap the result is
/// exceedingly rare.
///
pub trait Node: Into<NodeKey> {
  type Output: Clone + fmt::Debug + Into<NodeResult> + TryFrom<NodeResult> + Send + 'static;

  fn run(self, context: Context) -> NodeFuture<Self::Output>;
}

///
/// A Node that selects a product for a subject.
///
/// A Select can be satisfied by multiple sources, but fails if multiple sources produce a value.
/// The 'variants' field represents variant configuration that is propagated to dependencies. When
/// a task needs to consume a product as configured by the variants map, it can pass variant_key,
/// which matches a 'variant' value to restrict the names of values selected by a SelectNode.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub subject: Key,
  pub variants: Variants,
  pub selector: selectors::Select,
  entries: rule_graph::Entries,
}

impl Select {
  pub fn new(
    product: TypeConstraint,
    subject: Key,
    variants: Variants,
    edges: &rule_graph::RuleEdges,
  ) -> Select {
    let selector = selectors::Select::without_variant(product);
    let select_key = rule_graph::SelectKey::JustSelect(selector.clone());
    Select {
      selector: selector,
      subject: subject,
      variants: variants,
      entries: edges.entries_for(&select_key),
    }
  }

  pub fn new_with_entries(
    product: TypeConstraint,
    subject: Key,
    variants: Variants,
    entries: rule_graph::Entries,
  ) -> Select {
    let selector = selectors::Select::without_variant(product);
    Select {
      selector: selector,
      subject: subject,
      variants: variants,
      entries: entries,
    }
  }

  pub fn new_with_selector(
    selector: selectors::Select,
    subject: Key,
    variants: Variants,
    edges: &rule_graph::RuleEdges,
  ) -> Select {
    let select_key = rule_graph::SelectKey::JustSelect(selector.clone());
    Select {
      selector: selector,
      subject: subject,
      variants: variants,
      entries: edges
        .entries_for(&select_key)
        .into_iter()
        .filter(|e| e.matches_subject_type(subject.type_id().clone()))
        .collect(),
    }
  }

  fn product(&self) -> &TypeConstraint {
    &self.selector.product
  }

  fn select_literal_single<'a>(
    &self,
    candidate: &'a Value,
    variant_value: &Option<String>,
  ) -> bool {
    if !externs::satisfied_by(&self.selector.product, candidate) {
      return false;
    }
    return match variant_value {
      &Some(ref vv) if externs::project_str(candidate, "name") != *vv =>
        // There is a variant value, and it doesn't match.
        false,
      _ =>
        true,
    };
  }

  ///
  /// Looks for has-a or is-a relationships between the given value and the requested product.
  ///
  /// Returns the resulting product value, or None if no match was made.
  ///
  fn select_literal(
    &self,
    context: &Context,
    candidate: Value,
    variant_value: &Option<String>,
  ) -> Option<Value> {
    // Check whether the subject is-a instance of the product.
    if self.select_literal_single(&candidate, variant_value) {
      return Some(candidate);
    }

    // Else, check whether it has-a instance of the product.
    // TODO: returning only the first literal configuration of a given type/variant. Need to
    // define mergeability for products.
    if externs::satisfied_by(&context.core.types.has_products, &candidate) {
      for child in externs::project_multi(&candidate, "products") {
        if self.select_literal_single(&child, variant_value) {
          return Some(child);
        }
      }
    }
    None
  }

  ///
  /// Given the results of configured Task nodes, select a single successful value, or fail.
  ///
  fn choose_task_result(
    &self,
    context: Context,
    results: Vec<Result<Value, Failure>>,
    variant_value: &Option<String>,
  ) -> Result<Value, Failure> {
    let mut matches = Vec::new();
    let mut max_noop = Noop::NoTask;
    for result in results {
      match result {
        Ok(value) => {
          if let Some(v) = self.select_literal(&context, value, variant_value) {
            matches.push(v);
          }
        }
        Err(err) => {
          match err {
            Failure::Noop(noop) => {
              // Record the highest priority Noop value.
              if noop > max_noop {
                max_noop = noop;
              }
              continue;
            }
            i @ Failure::Invalidated => return Err(i),
            f @ Failure::Throw(..) => return Err(f),
          }
        }
      }
    }

    if matches.len() > 1 {
      // TODO: Multiple successful tasks are not currently supported. We could allow for this
      // by adding support for "mergeable" products. see:
      //   https://github.com/pantsbuild/pants/issues/2526
      return Err(throw("Conflicting values produced for subject and type."));
    }

    match matches.pop() {
      Some(matched) =>
        // Exactly one value was available.
        Ok(matched),
      None =>
        // Propagate the highest priority Noop value.
        Err(Failure::Noop(max_noop)),
    }
  }

  fn snapshot(&self, context: &Context, entry: &rule_graph::Entry) -> NodeFuture<fs::Snapshot> {
    let ref edges = context
      .core
      .rule_graph
      .edges_for_inner(entry)
      .expect("Expected edges to exist for Snapshot intrinsic.");
    // Compute PathGlobs for the subject.
    let context = context.clone();
    Select::new(
      context.core.types.path_globs.clone(),
      self.subject.clone(),
      self.variants.clone(),
      edges,
    ).run(context.clone())
      .and_then(move |path_globs_val| context.get(Snapshot(externs::key_for(path_globs_val))))
      .to_boxed()
  }

  fn execute_process(
    &self,
    context: &Context,
    entry: &rule_graph::Entry,
  ) -> NodeFuture<ProcessResult> {
    let ref edges = context
      .core
      .rule_graph
      .edges_for_inner(entry)
      .expect("Expected edges to exist for ExecuteProcess intrinsic.");
    // Compute an ExecuteProcessRequest for the subject.
    let context = context.clone();
    Select::new(
      context.core.types.process_request.clone(),
      self.subject.clone(),
      self.variants.clone(),
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
  /// Return Futures for each Task/Node that might be able to compute the given product for the
  /// given subject and variants.
  ///
  fn gen_nodes(&self, context: &Context) -> Vec<NodeFuture<Value>> {
    if let Some(&(_, ref value)) = context.core.tasks.gen_singleton(self.product()) {
      return vec![future::ok(value.clone()).to_boxed()];
    }

    self
      .entries
      .iter()
      .map(
        |entry| match context.core.rule_graph.rule_for_inner(entry) {
          &rule_graph::Rule::Task(ref task) => context.get(Task {
            subject: self.subject.clone(),
            product: self.product().clone(),
            variants: self.variants.clone(),
            task: task.clone(),
            entry: Arc::new(entry.clone()),
          }),
          &rule_graph::Rule::Intrinsic(Intrinsic {
            kind: IntrinsicKind::Snapshot,
            ..
          }) => {
            let context = context.clone();
            self
              .snapshot(&context, &entry)
              .map(move |snapshot| Snapshot::store_snapshot(&context.core, &snapshot))
              .to_boxed()
          }
          &rule_graph::Rule::Intrinsic(Intrinsic {
            kind: IntrinsicKind::FilesContent,
            ..
          }) => {
            let ref edges = context
              .core
              .rule_graph
              .edges_for_inner(entry)
              .expect("Expected edges to exist for FilesContent intrinsic.");
            let context = context.clone();
            Select::new(
              context.core.types.directory_digest.clone(),
              self.subject.clone(),
              self.variants.clone(),
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
                      .contents_for_directory(directory)
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
              .execute_process(&context, &entry)
              .map(move |result| {
                externs::unsafe_call(
                  &context.core.types.construct_process_result,
                  &[
                    externs::store_bytes(&result.0.stdout),
                    externs::store_bytes(&result.0.stderr),
                    externs::store_i64(result.0.exit_code as i64),
                    Snapshot::store_directory(&context.core, &result.0.output_directory),
                  ],
                )
              })
              .to_boxed()
          }
        },
      )
      .collect::<Vec<NodeFuture<Value>>>()
  }
}

// TODO: This is a Node only because it is used as a root in the graph, but it should never be
// requested using context.get
impl Node for Select {
  type Output = Value;

  fn run(self, context: Context) -> NodeFuture<Value> {
    // TODO add back support for variants https://github.com/pantsbuild/pants/issues/4020

    // If there is a variant_key, see whether it has been configured; if not, no match.
    let variant_value: Option<String> = match self.selector.variant_key {
      Some(ref variant_key) => {
        let variant_value = self.variants.find(variant_key);
        if variant_value.is_none() {
          return err(Failure::Noop(Noop::NoVariant));
        }
        variant_value.map(|v| v.to_string())
      }
      None => None,
    };

    // If the Subject "is a" or "has a" Product, then we're done.
    if let Some(literal_value) =
      self.select_literal(&context, externs::val_for(&self.subject), &variant_value)
    {
      return ok(literal_value);
    }

    // Else, attempt to use the configured tasks to compute the value.
    let deps_future = future::join_all(
      self
        .gen_nodes(&context)
        .into_iter()
        .map(|node_future| {
          // Don't fail the join if one fails.
          node_future.then(|r| future::ok(r))
        })
        .collect::<Vec<_>>(),
    );

    let variant_value = variant_value.map(|s| s.to_string());
    deps_future
      .and_then(move |dep_results| {
        future::result(self.choose_task_result(context, dep_results, &variant_value))
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
      return Err(format!("Error parsing env: odd number of parts"));
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
      .map(|path: String| PathBuf::from(path))
      .collect();

    let timeout_str = externs::project_str(&value, "timeout_seconds");
    let timeout_in_seconds = timeout_str
      .parse::<f64>()
      .map_err(|err| format!("Timeout was not a float: {:?}", err))?;

    let description = externs::project_str(&value, "description");

    Ok(ExecuteProcess(process_execution::ExecuteProcessRequest {
      argv: externs::project_multi_strs(&value, "argv"),
      env: env,
      input_files: digest,
      output_files: output_files,
      timeout: Duration::from_millis((timeout_in_seconds * 1000.0) as u64),
      description: description,
    }))
  }
}

#[derive(Clone, Debug)]
pub struct ProcessResult(process_execution::ExecuteProcessResult);

impl Node for ExecuteProcess {
  type Output = ProcessResult;

  fn run(self, context: Context) -> NodeFuture<ProcessResult> {
    let request = self.0;

    context
      .core
      .command_runner
      .run(request)
      .map(|result| ProcessResult(result))
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

#[derive(Clone, Debug)]
pub struct LinkDest(PathBuf);

impl Node for ReadLink {
  type Output = LinkDest;

  fn run(self, context: Context) -> NodeFuture<LinkDest> {
    let link = self.0.clone();
    context
      .core
      .vfs
      .read_link(&self.0)
      .map(|dest_path| LinkDest(dest_path))
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

impl Node for DigestFile {
  type Output = hashing::Digest;

  fn run(self, context: Context) -> NodeFuture<hashing::Digest> {
    let file = self.0.clone();
    context
      .core
      .vfs
      .read_file(&self.0)
      .map_err(move |e| {
        throw(&format!(
          "Error reading file {:?}: {}",
          file,
          e.description()
        ))
      })
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

#[derive(Clone, Debug)]
pub struct DirectoryListing(Vec<fs::Stat>);

impl Node for Scandir {
  type Output = DirectoryListing;

  fn run(self, context: Context) -> NodeFuture<DirectoryListing> {
    let dir = self.0.clone();
    context
      .core
      .vfs
      .scandir(&self.0)
      .then(move |listing_res| match listing_res {
        Ok(listing) => Ok(DirectoryListing(listing)),
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
/// TODO: ???
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
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
        fs::Snapshot::from_path_stats(context.core.store.clone(), context.clone(), path_stats)
          .map_err(move |e| format!("Snapshot failed: {}", e))
      })
      .map_err(|e| throw(&e))
      .to_boxed()
  }

  pub fn lift_path_globs(item: &Value) -> Result<PathGlobs, String> {
    let include = externs::project_multi_strs(item, "include");
    let exclude = externs::project_multi_strs(item, "exclude");
    let glob_match_error_behavior = externs::project_str(item, "glob_match_error_behavior");
    let strict_glob_matching = StrictGlobMatching::create(glob_match_error_behavior)?;
    PathGlobs::create_with_match_behavior(
      &include,
      &exclude,
      strict_glob_matching,
    ).map_err(|e| {
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
        externs::store_bytes(item.0.to_hex().as_bytes()),
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
    externs::store_bytes(item.as_os_str().as_bytes())
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

  fn store_files_content(context: &Context, item: &Vec<FileContent>) -> Value {
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

impl Node for Snapshot {
  type Output = fs::Snapshot;

  fn run(self, context: Context) -> NodeFuture<fs::Snapshot> {
    future::result(Self::lift_path_globs(&externs::val_for(&self.0)))
      .map_err(|e| throw(&format!("Failed to parse PathGlobs: {}", e)))
      .and_then(move |path_globs| Self::create(context, path_globs))
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
  subject: Key,
  product: TypeConstraint,
  variants: Variants,
  task: tasks::Task,
  entry: Arc<rule_graph::Entry>,
}

impl Task {
  fn gen_get(
    context: &Context,
    entry: Arc<rule_graph::Entry>,
    gets: Vec<externs::Get>,
  ) -> NodeFuture<Vec<Value>> {
    let get_futures = gets
      .into_iter()
      .map(|get| {
        let externs::Get(product, subject) = get;
        let entries = context
          .core
          .rule_graph
          .edges_for_inner(&entry)
          .expect("edges for task exist.")
          .entries_for(&rule_graph::SelectKey::JustGet(selectors::Get {
            product: product,
            subject: subject.type_id().clone(),
          }));
        Select::new_with_entries(product, subject, Default::default(), entries)
          .run(context.clone())
          .map_err(|e| was_required(e))
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
          externs::GeneratorResponse::Get(get) => Self::gen_get(&context, entry, vec![get])
            .map(|vs| future::Loop::Continue(vs.into_iter().next().unwrap()))
            .to_boxed(),
          externs::GeneratorResponse::GetMulti(gets) => Self::gen_get(&context, entry, gets)
            .map(|vs| future::Loop::Continue(externs::store_tuple(&vs)))
            .to_boxed(),
          externs::GeneratorResponse::Break(val) => future::ok(future::Loop::Break(val)).to_boxed(),
        }
      })
    }).to_boxed()
  }
}

impl Node for Task {
  type Output = Value;

  fn run(self, context: Context) -> NodeFuture<Value> {
    let deps = {
      let ref edges = context
        .core
        .rule_graph
        .edges_for_inner(&self.entry)
        .expect("edges for task exist.");
      let subject = self.subject;
      let variants = self.variants;
      future::join_all(
        self
          .task
          .clause
          .into_iter()
          .map(|s| {
            Select::new_with_selector(s, subject.clone(), variants.clone(), edges)
              .run(context.clone())
          })
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
  pub fn format(&self) -> String {
    fn keystr(key: &Key) -> String {
      externs::key_to_str(&key)
    }
    fn typstr(tc: &TypeConstraint) -> String {
      externs::key_to_str(&tc.0)
    }
    match self {
      &NodeKey::DigestFile(ref s) => format!("DigestFile({:?})", s.0),
      &NodeKey::ExecuteProcess(ref s) => format!("ExecuteProcess({:?}", s.0),
      &NodeKey::ReadLink(ref s) => format!("ReadLink({:?})", s.0),
      &NodeKey::Scandir(ref s) => format!("Scandir({:?})", s.0),
      &NodeKey::Select(ref s) => format!(
        "Select({}, {})",
        keystr(&s.subject),
        typstr(&s.selector.product)
      ),
      &NodeKey::Task(ref s) => format!(
        "Task({}, {}, {})",
        externs::project_str(&externs::val_for(&s.task.func.0), "__name__"),
        keystr(&s.subject),
        typstr(&s.product)
      ),
      // TODO(cosmicexplorer): why aren't we implementing an fmt::Debug for all of these nodes?
      &NodeKey::Snapshot(ref s) => format!("{:?}", s),
    }
  }

  pub fn product_str(&self) -> String {
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

  ///
  /// If this NodeKey represents an FS operation, returns its Path.
  ///
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
  type Output = NodeResult;

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
}

#[derive(Clone, Debug)]
pub enum NodeResult {
  Unit,
  Digest(hashing::Digest),
  DirectoryListing(DirectoryListing),
  LinkDest(LinkDest),
  ProcessResult(ProcessResult),
  Snapshot(fs::Snapshot),
  Value(Value),
}

impl From<()> for NodeResult {
  fn from(_: ()) -> Self {
    NodeResult::Unit
  }
}

impl From<Value> for NodeResult {
  fn from(v: Value) -> Self {
    NodeResult::Value(v)
  }
}

impl From<fs::Snapshot> for NodeResult {
  fn from(v: fs::Snapshot) -> Self {
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

impl From<DirectoryListing> for NodeResult {
  fn from(v: DirectoryListing) -> Self {
    NodeResult::DirectoryListing(v)
  }
}

// TODO: These traits exist in the stdlib, but are marked unstable.
//   see https://github.com/rust-lang/rust/issues/33417
pub trait TryFrom<T>: Sized {
  type Err;
  fn try_from(T) -> Result<Self, Self::Err>;
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

impl TryFrom<NodeResult> for () {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::Unit => Ok(()),
      _ => Err(()),
    }
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

impl TryFrom<NodeResult> for fs::Snapshot {
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

impl TryFrom<NodeResult> for DirectoryListing {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::DirectoryListing(v) => Ok(v),
      _ => Err(()),
    }
  }
}
