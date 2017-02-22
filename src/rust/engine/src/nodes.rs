// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).


use std::fmt;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use futures::future::{self, BoxFuture, Future};

use context::Core;
use core::{Function, Key, TypeConstraint, Value, Variants};
use externs;
use fs::{
  self,
  Dir,
  File,
  FileContent,
  Link,
  PathGlobs,
  PathStat,
  Stat,
  VFS,
};
use graph::EntryId;
use handles::maybe_drain_handles;
use selectors::{self, Selector};
use tasks;


#[derive(Debug, Clone)]
pub enum Failure {
  Noop(&'static str, Option<NodeKey>),
  Throw(Value),
}

pub type NodeFuture<T> = BoxFuture<T, Failure>;

/**
 * TODO: Move to the `context` module.
 */
#[derive(Clone)]
pub struct Context {
  entry_id: EntryId,
  core: Arc<Core>,
}

impl Context {
  pub fn new(entry_id: EntryId, core: Arc<Core>) -> Context {
    Context {
      entry_id: entry_id,
      core: core,
    }
  }

  /**
   * Get the future value for the given Node implementation.
   */
  fn get<N: Node>(&self, node: N) -> NodeFuture<N::Output> {
    // TODO: Odd place for this... could do it periodically in the background?
    maybe_drain_handles().map(|handles| {
      externs::drop_handles(handles);
    });

    self.core.graph.get(self.entry_id, self, node)
  }

  fn has_products(&self, item: &Value) -> bool {
    externs::satisfied_by(&self.core.types.has_products, item)
  }

  /**
   * Returns the `name` field of the given item.
   *
   * TODO: There is no check that the object _has_ a name field.
   */
  fn field_name(&self, item: &Value) -> String {
    externs::project_str(item, self.core.tasks.field_name.as_str())
  }

  fn field_products(&self, item: &Value) -> Vec<Value> {
    externs::project_multi(item, &self.core.tasks.field_products)
  }

  /**
   * NB: Panics on failure. Only recommended for use with built-in functions, such as
   * those configured in types::Types.
   */
  fn invoke_unsafe(&self, func: &Function, args: &Vec<Value>) -> Value {
    let func_val = externs::val_for_id(func.0);
    externs::invoke_runnable(&func_val, args, false)
      .unwrap_or_else(|e| {
        panic!(
          "Core function `{}` failed: {}",
          externs::id_to_str(func.0),
          externs::val_to_str(&e)
        );
      })
  }

  fn store_path(&self, item: &Path) -> Value {
    externs::store_bytes(item.as_os_str().as_bytes())
  }

  fn store_path_stat(&self, item: &PathStat) -> Value {
    let args =
      match item {
        &PathStat::Dir { ref path, ref stat } =>
          vec![self.store_path(path), self.store_dir(stat)],
        &PathStat::File { ref path, ref stat } =>
          vec![self.store_path(path), self.store_file(stat)],
      };
    self.invoke_unsafe(&self.core.types.construct_path_stat, &args)
  }

  fn store_dir(&self, item: &Dir) -> Value {
    let args = vec![self.store_path(item.0.as_path())];
    self.invoke_unsafe(&self.core.types.construct_dir, &args)
  }

  fn store_file(&self, item: &File) -> Value {
    let args = vec![self.store_path(item.0.as_path())];
    self.invoke_unsafe(&self.core.types.construct_file, &args)
  }

  fn store_snapshot(&self, item: &fs::Snapshot) -> Value {
    let path_stats: Vec<_> =
      item.path_stats.iter()
        .map(|ps| self.store_path_stat(ps))
        .collect();
    self.invoke_unsafe(
      &self.core.types.construct_snapshot,
      &vec![
        externs::store_bytes(&item.fingerprint.0),
        externs::store_list(path_stats.iter().collect(), false),
      ],
    )
  }

  fn store_file_content(&self, item: &FileContent) -> Value {
    self.invoke_unsafe(
      &self.core.types.construct_file_content,
      &vec![
        self.store_path(&item.path),
        externs::store_bytes(&item.content),
      ],
    )
  }

  fn store_files_content(&self, item: &Vec<FileContent>) -> Value {
    let entries: Vec<_> = item.iter().map(|e| self.store_file_content(e)).collect();
    self.invoke_unsafe(
      &self.core.types.construct_files_content,
      &vec![
        externs::store_list(entries.iter().collect(), false),
      ],
    )
  }

  fn project_multi_strs(&self, item: &Value, field: &str) -> Vec<String> {
    externs::project_multi(item, field).iter()
      .map(|v| externs::val_to_str(v))
      .collect()
  }

  fn type_path_globs(&self) -> &TypeConstraint {
    &self.core.types.path_globs
  }

  fn lift_path_globs(&self, item: &Value) -> Result<PathGlobs, String> {
    let include = self.project_multi_strs(item, &self.core.tasks.field_include);
    let exclude = self.project_multi_strs(item, &self.core.tasks.field_exclude);
    PathGlobs::create(&include, &exclude)
      .map_err(|e| {
        format!("Failed to parse PathGlobs for include({:?}), exclude({:?}): {}", include, exclude, e)
      })
  }

  /**
   * Creates a Throw state with the given exception message.
   */
  fn throw(&self, msg: &str) -> Failure {
    Failure::Throw(externs::create_exception(msg))
  }

  fn invoke_runnable(&self, func: &Value, args: &Vec<Value>, cacheable: bool) -> Result<Value, Failure> {
    externs::invoke_runnable(func, args, cacheable)
      .map_err(|v| Failure::Throw(v))
  }

  /**
   * A helper to indicate that the value represented by the Failure was an optional value.
   */
  fn was_optional(&self, failure: Failure, msg: &'static str) -> Failure {
    match failure {
      Failure::Noop(..) => Failure::Noop(msg, None),
      f => f,
    }
  }

  /**
   * A helper to indicate that the value represented by the Failure was required, and thus
   * fatal if not present.
   */
  fn was_required(&self, failure: Failure) -> Failure {
    match failure {
      Failure::Noop(..) => self.throw("No source of required dependencies"),
      f => f,
    }
  }

  fn ok<O: Send + 'static>(&self, value: O) -> NodeFuture<O> {
    future::ok(value).boxed()
  }

  fn err<O: Send + 'static>(&self, failure: Failure) -> NodeFuture<O> {
    future::err(failure).boxed()
  }
}

pub trait ContextFactory {
  fn create(&self, entry_id: EntryId) -> Context;
}

impl ContextFactory for Context {
  /**
   * Clones this Context for a new EntryId. Because the Core of the context is an Arc, this
   * is a shallow clone.
   */
  fn create(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: entry_id,
      core: self.core.clone(),
    }
  }
}

impl VFS<Failure> for Context {
  fn read_link(&self, link: Link) -> NodeFuture<PathBuf> {
    self.get(ReadLink(link)).map(|res| res.0).boxed()
  }

  fn scandir(&self, dir: Dir) -> NodeFuture<Vec<Stat>> {
    self.get(Scandir(dir)).map(|res| res.0).boxed()
  }

  fn ignore<P: AsRef<Path>>(&self, path: P, is_dir: bool) -> bool {
    !self.core.vfs.ignore.matched(path, is_dir).is_none()
  }
}

/**
 * Defines executing a cacheable/memoizable step for the given context.
 *
 * The Output type of a Node is bounded to values that can be stored and retrieved from
 * the NodeResult enum. Due to the semantics of memoization, retrieving the typed result
 * stored inside the NodeResult requires an implementation of TryFrom<NodeResult>. But the
 * combination of bounds at usage sites should mean that a failure to unwrap the result is
 * exceedingly rare.
 */
pub trait Node: Into<NodeKey> {
  type Output: Clone + fmt::Debug + Into<NodeResult> + TryFrom<NodeResult> + Send + 'static;

  fn run(&self, context: Context) -> NodeFuture<Self::Output>;
}

/**
 * A Node that selects a product for a subject.
 *
 * A Select can be satisfied by multiple sources, but fails if multiple sources produce a value. The
 * 'variants' field represents variant configuration that is propagated to dependencies. When
 * a task needs to consume a product as configured by the variants map, it can pass variant_key,
 * which matches a 'variant' value to restrict the names of values selected by a SelectNode.
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub subject: Key,
  pub variants: Variants,
  pub selector: selectors::Select,
}

impl Select {
  pub fn new(product: TypeConstraint, subject: Key, variants: Variants) -> Select {
    Select {
      selector: selectors::Select { product: product, variant_key: None },
      subject: subject,
      variants: variants,
    }
  }

  fn product(&self) -> &TypeConstraint {
    &self.selector.product
  }

  fn select_literal_single<'a>(
    &self,
    context: &Context,
    candidate: &'a Value,
    variant_value: &Option<String>
  ) -> bool {
    if !externs::satisfied_by(&self.selector.product, candidate) {
      return false;
    }
    return match variant_value {
      &Some(ref vv) if context.field_name(candidate) != *vv =>
        // There is a variant value, and it doesn't match.
        false,
      _ =>
        true,
    }
  }

  /**
   * Looks for has-a or is-a relationships between the given value and the requested product.
   *
   * Returns the resulting product value, or None if no match was made.
   */
  fn select_literal(
    &self,
    context: &Context,
    candidate: Value,
    variant_value: &Option<String>
  ) -> Option<Value> {
    // Check whether the subject is-a instance of the product.
    if self.select_literal_single(context, &candidate, variant_value) {
      return Some(candidate)
    }

    // Else, check whether it has-a instance of the product.
    // TODO: returning only the first literal configuration of a given type/variant. Need to
    // define mergeability for products.
    if context.has_products(&candidate) {
      for child in context.field_products(&candidate) {
        if self.select_literal_single(context, &child, variant_value) {
          return Some(child);
        }
      }
    }
    return None;
  }

  /**
   * Given the results of configured Task nodes, select a single successful value, or fail.
   */
  fn choose_task_result(
    &self,
    context: Context,
    results: Vec<Result<Value, Failure>>,
    variant_value: &Option<String>,
  ) -> Result<Value, Failure> {
    let mut matches = Vec::new();
    for result in results {
      match result {
        Ok(value) => {
          if let Some(v) = self.select_literal(&context, value, variant_value) {
            matches.push(v);
          }
        },
        Err(err) => {
          match err {
            Failure::Noop(_, _) =>
              continue,
            f @ Failure::Throw(_) =>
              return Err(f),
          }
        },
      }
    }

    if matches.len() > 1 {
      // TODO: Multiple successful tasks are not currently supported. We should allow for this
      // by adding support for "mergeable" products. see:
      //   https://github.com/pantsbuild/pants/issues/2526
      return Err(context.throw("Conflicting values produced for subject and type."));
    }

    match matches.pop() {
      Some(matched) =>
        // Exactly one value was available.
        Ok(matched),
      None =>
        Err(
          Failure::Noop("No task was available to compute the value.", None)
        ),
    }
  }

  /**
   * Gets a Snapshot for the current subject.
   */
  fn get_snapshot(&self, context: &Context) -> NodeFuture<fs::Snapshot> {
    // TODO: Hacky... should have an intermediate Node to Select PathGlobs for the subject
    // before executing, and then treat this as an intrinsic. Otherwise, Snapshots for
    // different subjects but identical PathGlobs will cause redundant work.
    context.get(
      Snapshot {
        subject: self.subject.clone(),
        product: self.product().clone(),
        variants: self.variants.clone(),
      }
    )
  }

  /**
   * Return Futures for each Task/Node that might be able to compute the given product for the
   * given subject and variants.
   */
  fn gen_nodes(&self, context: &Context) -> Vec<NodeFuture<Value>> {
    // TODO: These `product==` hooks are hacky.
    if self.product() == &context.core.types.snapshot {
      // If the requested product is a Snapshot, execute a Snapshot Node and then lower to a Value
      // for this caller.
      let context = context.clone();
      vec![
        self.get_snapshot(&context)
          .map(move |snapshot| context.store_snapshot(&snapshot))
          .boxed()
      ]
    } else if self.product() == &context.core.types.files_content {
      // If the requested product is FilesContent, request a Snapshot and lower it as FilesContent.
      let context = context.clone();
      vec![
        self.get_snapshot(&context)
          .and_then(move |snapshot|
            // Request the file contents of the Snapshot, and then store them.
            context.core.snapshots.contents_for(&context.core.vfs, snapshot)
              .then(move |files_content_res| match files_content_res {
                Ok(files_content) => Ok(context.store_files_content(&files_content)),
                Err(e) => Err(context.throw(&e)),
              })
          )
          .boxed()
      ]
    } else {
      context.core.tasks.gen_tasks(self.subject.type_id(), self.product())
        .map(|tasks| {
          tasks.iter()
            .map(|task|
              context.get(
                Task {
                  subject: self.subject.clone(),
                  product: self.product().clone(),
                  variants: self.variants.clone(),
                  task: task.clone(),
                }
              )
            )
            .collect()
        })
        .unwrap_or_else(|| Vec::new())
    }
  }
}

impl Node for Select {
  type Output = Value;

  fn run(&self, context: Context) -> NodeFuture<Value> {
    // TODO add back support for variants https://github.com/pantsbuild/pants/issues/4020

    // If there is a variant_key, see whether it has been configured; if not, no match.
    let variant_value: Option<String> =
      match self.selector.variant_key {
        Some(ref variant_key) => {
          let variant_value = self.variants.find(variant_key);
          if variant_value.is_none() {
            return context.err(
              Failure::Noop("A matching variant key was not configured in variants.", None)
            );
          }
          variant_value.map(|v| v.to_string())
        },
        None => None,
      };

    // If the Subject "is a" or "has a" Product, then we're done.
    if let Some(literal_value) = self.select_literal(&context, externs::val_for(&self.subject), &variant_value) {
      return context.ok(literal_value);
    }

    // Else, attempt to use the configured tasks to compute the value.
    let deps_future =
      future::join_all(
        self.gen_nodes(&context).into_iter()
          .map(|node_future| {
            // Don't fail the join if one fails.
            node_future.then(|r| future::ok(r))
          })
          .collect::<Vec<_>>()
      );

    let variant_value = variant_value.map(|s| s.to_string());
    let node = self.clone();
    deps_future
      .and_then(move |dep_results| {
        future::result(node.choose_task_result(context, dep_results, &variant_value))
      })
      .boxed()
  }
}

impl From<Select> for NodeKey {
  fn from(n: Select) -> Self {
    NodeKey::Select(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectLiteral,
}

impl Node for SelectLiteral {
  type Output = Value;

  fn run(&self, context: Context) -> NodeFuture<Value> {
    context.ok(externs::val_for(&self.selector.subject))
  }
}

impl From<SelectLiteral> for NodeKey {
  fn from(n: SelectLiteral) -> Self {
    NodeKey::SelectLiteral(n)
  }
}

/**
 * A Node that selects the given Product for each of the items in `field` on `dep_product`.
 *
 * Begins by selecting the `dep_product` for the subject, and then selects a product for each
 * member of a collection named `field` on the dep_product.
 *
 * The value produced by this Node guarantees that the order of the provided values matches the
 * order of declaration in the list `field` of the `dep_product`.
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectDependencies {
  pub subject: Key,
  pub variants: Variants,
  pub selector: selectors::SelectDependencies,
}

impl SelectDependencies {
  pub fn new(
    selector: selectors::SelectDependencies,
    subject: Key,
    variants: Variants
  ) -> SelectDependencies {
    SelectDependencies {
      subject: subject,
      variants: variants,
      selector: selector,
    }
  }

  fn get_dep(&self, context: &Context, dep_subject: &Value) -> NodeFuture<Value> {
    // TODO: This method needs to consider whether the `dep_subject` is an Address,
    // and if so, attempt to parse Variants there. See:
    //   https://github.com/pantsbuild/pants/issues/4020

    let dep_subject_key = externs::key_for(dep_subject);
    if self.selector.transitive {
      // After the root has been expanded, a traversal continues with dep_product == product.
      let mut selector = self.selector.clone();
      selector.dep_product = selector.product;
      context.get(
        SelectDependencies {
          subject: dep_subject_key,
          variants: self.variants.clone(),
          selector: selector,
        }
      )
    } else {
      context.get(Select::new(self.selector.product.clone(), dep_subject_key, self.variants.clone()))
    }
  }

  fn store(&self, dep_product: &Value, dep_values: Vec<&Value>) -> Value {
    if self.selector.transitive && externs::satisfied_by(&self.selector.product, dep_product)  {
      // If the dep_product is an inner node in the traversal, prepend it to the list of
      // items to be merged.
      // TODO: would be nice to do this in one operation.
      let prepend = externs::store_list(vec![dep_product], false);
      let mut prepended = dep_values;
      prepended.insert(0, &prepend);
      externs::store_list(prepended, self.selector.transitive)
    } else {
      // Not an inner node, or not a traversal.
      externs::store_list(dep_values, self.selector.transitive)
    }
  }
}

impl Node for SelectDependencies {
  type Output = Value;

  fn run(&self, context: Context) -> NodeFuture<Value> {
    let node = self.clone();

    context
      .get(
        // Select the product holding the dependency list.
        Select::new(self.selector.dep_product, self.subject.clone(), self.variants.clone())
      )
      .then(move |dep_product_res| {
        match dep_product_res {
          Ok(dep_product) => {
            // The product and its dependency list are available: project them.
            let deps =
              future::join_all(
                externs::project_multi(&dep_product, &node.selector.field).iter()
                  .map(|dep_subject| node.get_dep(&context, &dep_subject))
                  .collect::<Vec<_>>()
              );
            deps
              .then(move |dep_values_res| {
                // Finally, store the resulting values.
                match dep_values_res {
                  Ok(dep_values) => {
                    Ok(node.store(&dep_product, dep_values.iter().collect()))
                  },
                  Err(failure) =>
                    Err(context.was_required(failure)),
                }
              })
              .boxed()
          },
          Err(failure) =>
            context.err(context.was_optional(failure, "No source of input product.")),
        }
      })
      .boxed()
  }
}

impl From<SelectDependencies> for NodeKey {
  fn from(n: SelectDependencies) -> Self {
    NodeKey::SelectDependencies(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

impl Node for SelectProjection {
  type Output = Value;

  fn run(&self, context: Context) -> NodeFuture<Value> {
    let node = self.clone();

    context
      .get(
        // Request the product we need to compute the subject.
        Select::new(self.selector.input_product, self.subject.clone(), self.variants.clone())
      )
      .then(move |dep_product_res| {
        match dep_product_res {
          Ok(dep_product) => {
            // And then project the relevant field.
            let projected_subject =
              externs::project(
                &dep_product,
                &node.selector.field,
                &node.selector.projected_subject
              );
            context
              .get(
                Select::new(
                  node.selector.product,
                  externs::key_for(&projected_subject),
                  node.variants.clone()
                )
              )
              .then(move |output_res| {
                // If the output product is available, return it.
                match output_res {
                  Ok(output) => Ok(output),
                  Err(failure) => Err(context.was_required(failure)),
                }
              })
              .boxed()
          },
          Err(failure) =>
            context.err(context.was_optional(failure, "No source of input product.")),
        }
      })
      .boxed()
  }
}

impl From<SelectProjection> for NodeKey {
  fn from(n: SelectProjection) -> Self {
    NodeKey::SelectProjection(n)
  }
}

/**
 * A Node that represents reading the destination of a symlink (non-recursively).
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ReadLink(Link);

#[derive(Clone, Debug)]
pub struct LinkDest(PathBuf);

impl Node for ReadLink {
  type Output = LinkDest;

  fn run(&self, context: Context) -> NodeFuture<LinkDest> {
    let link = self.0.clone();
    context.core.vfs.read_link(&self.0)
      .map(|dest_path| LinkDest(dest_path))
      .map_err(move |e|
        context.throw(&format!("Failed to read_link for {:?}: {:?}", link, e))
      )
      .boxed()
  }
}

impl From<ReadLink> for NodeKey {
  fn from(n: ReadLink) -> Self {
    NodeKey::ReadLink(n)
  }
}

/**
 * A Node that represents executing a directory listing that returns a Stat per directory
 * entry (generally in one syscall). No symlinks are expanded.
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Scandir(Dir);

#[derive(Clone, Debug)]
pub struct DirectoryListing(Vec<Stat>);

impl Node for Scandir {
  type Output = DirectoryListing;

  fn run(&self, context: Context) -> NodeFuture<DirectoryListing> {
    let dir = self.0.clone();
    context.core.vfs.scandir(&self.0)
      .map(|listing| DirectoryListing(listing))
      .map_err(move |e|
        context.throw(&format!("Failed to scandir for {:?}: {:?}", dir, e))
      )
      .boxed()
  }
}

impl From<Scandir> for NodeKey {
  fn from(n: Scandir) -> Self {
    NodeKey::Scandir(n)
  }
}

/**
 * A Node that captures an fs::Snapshot for the given subject.
 *
 * Begins by selecting PathGlobs for the subject, and then computes a Snapshot for the
 * PathStats matched by the PathGlobs.
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Snapshot {
  subject: Key,
  product: TypeConstraint,
  variants: Variants,
}

impl Snapshot {
  fn create(context: Context, path_globs: PathGlobs) -> NodeFuture<fs::Snapshot> {
    // Recursively expand PathGlobs into PathStats while tracking their dependencies.
    context
      .expand(path_globs)
      .then(move |path_stats_res| match path_stats_res {
        Ok(path_stats) => {
          // And then create a Snapshot.
          context.core.snapshots
            .create(&context.core.vfs, path_stats)
            .map_err(move |e| {
              context.throw(&format!("Snapshot failed: {}", e))
            })
            .boxed()
        },
        Err(e) =>
          context.err(context.throw(&format!("PathGlobs expansion failed: {:?}", e))),
      })
      .boxed()
  }
}

impl Node for Snapshot {
  type Output = fs::Snapshot;

  fn run(&self, context: Context) -> NodeFuture<fs::Snapshot> {
    // Compute and parse PathGlobs for the subject.
    context
      .get(
        Select::new(
          context.type_path_globs().clone(),
          self.subject.clone(),
          self.variants.clone()
        )
      )
      .then(move |path_globs_res| match path_globs_res {
        Ok(path_globs_val) => {
          match context.lift_path_globs(&path_globs_val) {
            Ok(pgs) =>
              Snapshot::create(context, pgs),
            Err(e) =>
              context.err(context.throw(&format!("Failed to parse PathGlobs: {}", e))),
          }
        },
        Err(failure) =>
          context.err(context.was_optional(failure, "No source of PathGlobs."))
      })
      .boxed()
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
}

impl Task {
  /**
   * TODO: Can/should inline execution of all of these.
   */
  fn get(&self, context: &Context, selector: Selector) -> NodeFuture<Value> {
    match selector {
      Selector::Select(s) =>
        context.get(Select {
          subject: self.subject.clone(),
          variants: self.variants.clone(),
          selector: s,
        }),
      Selector::SelectDependencies(s) =>
        context.get(SelectDependencies {
          subject: self.subject.clone(),
          variants: self.variants.clone(),
          selector: s,
        }),
      Selector::SelectProjection(s) =>
        context.get(SelectProjection {
          subject: self.subject.clone(),
          variants: self.variants.clone(),
          selector: s,
        }),
      Selector::SelectLiteral(s) =>
        context.get(SelectLiteral {
          subject: self.subject.clone(),
          variants: self.variants.clone(),
          selector: s,
        }),
    }
  }
}

impl Node for Task {
  type Output = Value;

  fn run(&self, context: Context) -> NodeFuture<Value> {
    let deps =
      future::join_all(
        self.task.clause.iter()
          .map(|selector| self.get(&context, selector.clone()))
          .collect::<Vec<_>>()
      );

    let task = self.task.clone();
    deps
      .then(move |deps_result| match deps_result {
        Ok(deps) =>
          context.invoke_runnable(
            &externs::val_for_id(task.func.0),
            &deps,
            task.cacheable,
          ),
        Err(err) =>
          Err(context.was_optional(err, "Missing at least one input.")),
      })
      .boxed()
  }
}

impl From<Task> for NodeKey {
  fn from(n: Task) -> Self {
    NodeKey::Task(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum NodeKey {
  ReadLink(ReadLink),
  Scandir(Scandir),
  Select(Select),
  SelectDependencies(SelectDependencies),
  SelectLiteral(SelectLiteral),
  SelectProjection(SelectProjection),
  Snapshot(Snapshot),
  Task(Task),
}

impl NodeKey {
  pub fn format(&self) -> String {
    fn keystr(key: &Key) -> String {
      externs::id_to_str(key.id())
    }
    fn typstr(tc: &TypeConstraint) -> String {
      externs::id_to_str(tc.0)
    }
    match self {
      &NodeKey::ReadLink(ref s) =>
        format!("ReadLink({:?})", s.0),
      &NodeKey::Scandir(ref s) =>
        format!("Scandir({:?})", s.0),
      &NodeKey::Select(ref s) =>
        format!("Select({}, {})", keystr(&s.subject), typstr(&s.selector.product)),
      &NodeKey::SelectLiteral(ref s) =>
        format!("Literal({})", keystr(&s.subject)),
      &NodeKey::SelectDependencies(ref s) =>
        format!("Dependencies({}, {})", keystr(&s.subject), typstr(&s.selector.product)),
      &NodeKey::SelectProjection(ref s) =>
        format!("Projection({}, {})", keystr(&s.subject), typstr(&s.selector.product)),
      &NodeKey::Task(ref s) =>
        format!(
          "Task({}, {}, {})",
          externs::id_to_str(s.task.func.0),
          keystr(&s.subject),
          typstr(&s.product)
        ),
      &NodeKey::Snapshot(ref s) =>
        format!("Snapshot({})", keystr(&s.subject)),
    }
  }

  pub fn product_str(&self) -> String {
    fn typstr(tc: &TypeConstraint) -> String {
      externs::id_to_str(tc.0)
    }
    match self {
      &NodeKey::Select(ref s) => typstr(&s.selector.product),
      &NodeKey::SelectLiteral(ref s) => typstr(&s.selector.product),
      &NodeKey::SelectDependencies(ref s) => typstr(&s.selector.product),
      &NodeKey::SelectProjection(ref s) => typstr(&s.selector.product),
      &NodeKey::Task(ref s) => typstr(&s.product),
      &NodeKey::Snapshot(..) => "Snapshot".to_string(),
      &NodeKey::ReadLink(..) => "LinkDest".to_string(),
      &NodeKey::Scandir(..) => "DirectoryListing".to_string(),
    }
  }

  /**
   * If this NodeKey represents an FS operation, returns its Path.
   */
  pub fn fs_subject(&self) -> Option<&Path> {
    match self {
      &NodeKey::ReadLink(ref s) => Some((s.0).0.as_path()),
      &NodeKey::Scandir(ref s) => Some((s.0).0.as_path()),
      _ => None,
    }
  }
}

impl Node for NodeKey {
  type Output = NodeResult;

  fn run(&self, context: Context) -> NodeFuture<NodeResult> {
    match self {
      &NodeKey::ReadLink(ref n) => n.run(context).map(|v| v.into()).boxed(),
      &NodeKey::Scandir(ref n) => n.run(context).map(|v| v.into()).boxed(),
      &NodeKey::Select(ref n) => n.run(context).map(|v| v.into()).boxed(),
      &NodeKey::SelectDependencies(ref n) => n.run(context).map(|v| v.into()).boxed(),
      &NodeKey::SelectLiteral(ref n) => n.run(context).map(|v| v.into()).boxed(),
      &NodeKey::SelectProjection(ref n) => n.run(context).map(|v| v.into()).boxed(),
      &NodeKey::Snapshot(ref n) => n.run(context).map(|v| v.into()).boxed(),
      &NodeKey::Task(ref n) => n.run(context).map(|v| v.into()).boxed(),
    }
  }
}

#[derive(Clone, Debug)]
pub enum NodeResult {
  DirectoryListing(DirectoryListing),
  LinkDest(LinkDest),
  Snapshot(fs::Snapshot),
  Value(Value),
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

impl<T, U> TryInto<U> for T where U: TryFrom<T> {
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

impl TryFrom<NodeResult> for fs::Snapshot {
  type Err = ();

  fn try_from(nr: NodeResult) -> Result<Self, ()> {
    match nr {
      NodeResult::Snapshot(v) => Ok(v),
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
