
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use futures::future::{BoxFuture, Future};
use futures::future;

use context::Core;
use core::{Field, Function, Key, TypeConstraint, TypeId, Value, Variants};
use externs::Externs;
use fs::{self, Dir, File, FSContext, Link, PathGlobs, PathStat, Stat};
use graph::EntryId;
use handles::maybe_drain_handles;
use selectors::{self, Selector};


#[derive(Debug)]
pub enum Failure {
  Noop(&'static str, Option<Node>),
  Throw(Value),
}

pub type NodeResult = Result<Value, Failure>;

pub type StepFuture = BoxFuture<Value, Failure>;

// Because multiple callers may wait on the same Node, the Future for a Node must be shareable.
pub type NodeFuture = future::Shared<StepFuture>;

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
   * Create Nodes for each Task that might be able to compute the given product for the
   * given subject and variants.
   *
   * (analogous to NodeBuilder.gen_nodes)
   */
  fn gen_nodes(&self, subject: &Key, product: &TypeConstraint, variants: &Variants) -> Vec<Node> {
    // If the requested product is a Snapshot, use a Snapshot Node.
    if product == self.type_snapshot() {
      vec![
        // TODO: Hack... should have an intermediate Node to Select PathGlobs for the subject
        // before executing, and then treat this as an intrinsic. Otherwise, Snapshots for
        // different subjects but identical PathGlobs will cause redundant work.
        Node::Snapshot(
          Snapshot {
            subject: subject.clone(),
            product: product.clone(),
            variants: variants.clone(),
          }
        )
      ]
    } else {
      self.core.tasks.gen_tasks(subject.type_id(), product)
        .map(|tasks| {
          tasks.iter()
            .map(|task|
              Node::Task(
                Task {
                  subject: subject.clone(),
                  product: product.clone(),
                  variants: variants.clone(),
                  selector: task.clone(),
                }
              )
            )
            .collect()
        })
        .unwrap_or_else(|| Vec::new())
    }
  }

  /**
   * Get the future value for the given Node.
   */
  fn get(&self, node: &Node) -> NodeFuture {
    self.core.graph.get(self.entry_id, self, node)
  }

  fn has_products(&self, item: &Value) -> bool {
    self.core.externs.satisfied_by(&self.core.types.has_products, item.type_id())
  }

  /**
   * Returns the `name` field of the given item.
   *
   * TODO: There are at least two hacks here. Because we don't have access to the appropriate
   * `str` type, we just assume that it has the same type as the name of the field. And more
   * importantly, there is no check that the object _has_ a name field.
   *
   * See https://github.com/pantsbuild/pants/issues/4207 about cleaning this up a bit.
   */
  fn field_name(&self, item: &Value) -> String {
    let name_val =
      self.project(
        item,
        &self.core.tasks.field_name,
        self.core.tasks.field_name.0.type_id()
      );
    self.core.externs.val_to_str(&name_val)
  }

  fn field_products(&self, item: &Value) -> Vec<Value> {
    self.project_multi(item, &self.core.tasks.field_products)
  }

  fn key_for(&self, val: &Value) -> Key {
    self.core.externs.key_for(val)
  }

  fn val_for(&self, key: &Key) -> Value {
    self.core.externs.val_for(key)
  }

  fn clone_val(&self, val: &Value) -> Value {
    self.core.externs.clone_val(val)
  }

  /**
   * NB: Panics on failure. Only recommended for use with built-in functions, such as
   * those configured in types::Types.
   */
  fn invoke_unsafe(&self, func: &Function, args: &Vec<Value>) -> Value {
    self.core.externs.invoke_runnable(func, args, false)
      .unwrap_or_else(|e| {
        panic!(
          "Core function `{}` failed: {}",
          self.core.externs.id_to_str(func.0),
          self.core.externs.val_to_str(&e)
        );
      })
  }

  /**
   * Stores a list of Keys, resulting in a Key for the list.
   */
  fn store_list(&self, items: Vec<&Value>, merge: bool) -> Value {
    self.core.externs.store_list(items, merge)
  }

  fn store_bytes(&self, item: &[u8]) -> Value {
    self.core.externs.store_bytes(item)
  }

  fn store_path(&self, item: &Path) -> Value {
    self.core.externs.store_bytes(item.as_os_str().as_bytes())
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

  fn store_link(&self, item: &Link) -> Value {
    let args = vec![self.store_path(item.0.as_path())];
    self.invoke_unsafe(&self.core.types.construct_link, &args)
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
        self.store_bytes(&item.fingerprint),
        self.store_list(path_stats.iter().collect(), false),
      ],
    )
  }

  /**
   * Calls back to Python for a satisfied_by check.
   */
  fn satisfied_by(&self, constraint: &TypeConstraint, cls: &TypeId) -> bool {
    self.core.externs.satisfied_by(constraint, cls)
  }

  /**
   * Calls back to Python to project a field.
   */
  fn project(&self, item: &Value, field: &Field, type_id: &TypeId) -> Value {
    self.core.externs.project(item, field, type_id)
  }

  /**
   * Calls back to Python to project a field representing a collection.
   */
  fn project_multi(&self, item: &Value, field: &Field) -> Vec<Value> {
    self.core.externs.project_multi(item, field)
  }

  fn project_multi_strs(&self, item: &Value, field: &Field) -> Vec<String> {
    self.core.externs.project_multi(item, field).iter()
      .map(|v| self.core.externs.val_to_str(v))
      .collect()
  }

  fn snapshot_root(&self) -> Dir {
    // TODO
    Dir(Path::new(".snapshot").to_owned())
  }

  fn build_root(&self) -> Dir {
    // TODO
    Dir(Path::new("").to_owned())
  }

  fn type_path_globs(&self) -> &TypeConstraint {
    &self.core.types.path_globs
  }

  fn type_snapshot(&self) -> &TypeConstraint {
    &self.core.types.snapshot
  }

  fn type_read_link(&self) -> &TypeConstraint {
    &self.core.types.read_link
  }

  fn type_directory_listing(&self) -> &TypeConstraint {
    &self.core.types.directory_listing
  }

  fn lift_path_globs(&self, item: &Value) -> Result<PathGlobs, String> {
    let include = self.project_multi_strs(item, &self.core.tasks.field_include);
    let exclude = self.project_multi_strs(item, &self.core.tasks.field_exclude);
    PathGlobs::create(&include, &exclude)
      .map_err(|e| {
        format!("Failed to parse PathGlobs for include({:?}), exclude({:?}): {}", include, exclude, e)
      })
  }

  fn lift_read_link(&self, item: &Value) -> PathBuf {
    self.core.externs.lift_read_link(item, &self.core.tasks.field_path)
  }

  fn lift_directory_listing(&self, item: &Value) -> Vec<Stat> {
    self.core.externs.lift_directory_listing(item)
  }

  /**
   * Creates a Throw state with the given exception message.
   */
  fn throw(&self, msg: &str) -> Failure {
    Failure::Throw(self.core.externs.create_exception(msg))
  }

  fn invoke_runnable(&self, func: &Function, args: &Vec<Value>, cacheable: bool) -> Result<Value, Failure> {
    self.core.externs.invoke_runnable(func, args, cacheable)
      .map_err(|v| Failure::Throw(v))
  }

  /**
   * A helper to take ownership of the given Failure, while indicating that the value
   * represented by the Failure was an optional value.
   */
  fn was_optional(&self, failure: future::SharedError<Failure>, msg: &'static str) -> Failure {
    match *failure {
      Failure::Noop(..) =>
        Failure::Noop(msg, None),
      Failure::Throw(ref msg) =>
        Failure::Throw(self.clone_val(msg)),
    }
  }

  /**
   * A helper to take ownership of the given Failure, while indicating that the value
   * represented by the Failure was required, and thus fatal if not present.
   */
  fn was_required(&self, failure: future::SharedError<Failure>) -> Failure {
    match *failure {
      Failure::Noop(..) =>
        self.throw("No source of required dependencies"),
      Failure::Throw(ref msg) =>
        Failure::Throw(self.clone_val(msg)),
    }
  }

  fn ok(&self, value: Value) -> StepFuture {
    future::ok(value).boxed()
  }

  fn err(&self, failure: Failure) -> StepFuture {
    future::err(failure).boxed()
  }
}

impl FSContext<Failure> for Context {
  fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, Failure> {
    let context = self.clone();
    self
      .get(
        &Node::create(
          Selector::select(self.type_read_link().clone()),
          self.key_for(&self.store_link(link)),
          Variants::default(),
        )
      )
      .then(move |read_link_res| {
        match read_link_res {
          Ok(ref read_link) =>
            Ok(context.lift_read_link(read_link)),
          Err(failure) =>
            Err(context.was_required(failure)),
        }
      })
      .boxed()
  }

  fn scandir(&self, dir: &Dir) -> BoxFuture<Vec<Stat>, Failure> {
    let context = self.clone();
    let node =
      Node::create(
        Selector::select(self.type_directory_listing().clone()),
        self.key_for(&self.store_dir(dir)),
        Variants::default(),
      );
    self.get(&node)
      .then(move |dir_listing_res| {
        match dir_listing_res {
          Ok(ref dir_listing) =>
            Ok(context.lift_directory_listing(dir_listing)),
          Err(failure) =>
            Err(context.was_required(failure)),
        }
      })
      .boxed()
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

/**
 * Defines executing a single step for the given context.
 */
trait Step {
  fn step(&self, context: Context) -> StepFuture;
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
  subject: Key,
  variants: Variants,
  selector: selectors::Select,
}

impl Select {
  fn product(&self) -> &TypeConstraint {
    &self.selector.product
  }

  fn select_literal_single<'a>(
    &self,
    context: &Context,
    candidate: &'a Value,
    variant_value: &Option<String>
  ) -> bool {
    if !context.satisfied_by(&self.selector.product, candidate.type_id()) {
      return false;
    }
    return match variant_value {
      &Some(ref vv) if context.field_name(candidate) != *vv =>
        // There is a variant value, and it doesn't match.
        false,
      _ =>
        true,
    };
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
    results: Vec<Result<future::SharedItem<Value>, future::SharedError<Failure>>>,
    variant_value: &Option<String>,
  ) -> Result<Value, Failure> {
    let mut matches = Vec::new();
    for result in results {
      match result {
        Ok(ref value) => {
          if let Some(v) = self.select_literal(&context, context.clone_val(value), variant_value) {
            matches.push(v);
          }
        },
        Err(err) => {
          match *err {
            Failure::Noop(_, _) =>
              continue,
            Failure::Throw(ref msg) =>
              return Err(Failure::Throw(context.clone_val(msg))),
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
}

impl Step for Select {
  fn step(&self, context: Context) -> StepFuture {
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
    if let Some(literal_value) = self.select_literal(&context, context.val_for(&self.subject), &variant_value) {
      return context.ok(literal_value);
    }

    // Else, attempt to use the configured tasks to compute the value.
    let deps_future =
      future::join_all(
        context.gen_nodes(&self.subject, self.product(), &self.variants).iter()
          .map(|task_node| {
            // Attempt to get the value of each task Node, but don't fail the join if one fails.
            context.get(&task_node).then(|r| future::ok(r))
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

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectLiteral,
}

impl Step for SelectLiteral {
  fn step(&self, context: Context) -> StepFuture {
    context.ok(context.val_for(&self.selector.subject))
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
  subject: Key,
  variants: Variants,
  selector: selectors::SelectDependencies,
}

impl SelectDependencies {
  fn dep_node(&self, context: &Context, dep_subject: &Value) -> Node {
    // TODO: This method needs to consider whether the `dep_subject` is an Address,
    // and if so, attempt to parse Variants there. See:
    //   https://github.com/pantsbuild/pants/issues/4020

    let dep_subject_key = context.key_for(dep_subject);
    if self.selector.transitive {
      // After the root has been expanded, a traversal continues with dep_product == product.
      let mut selector = self.selector.clone();
      selector.dep_product = selector.product;
      Node::create(
        Selector::SelectDependencies(selector),
        dep_subject_key,
        self.variants.clone()
      )
    } else {
      Node::create(Selector::select(self.selector.product), dep_subject_key, self.variants.clone())
    }
  }

  fn store(&self, context: &Context, dep_product: &Value, dep_values: Vec<&Value>) -> Value {
    if self.selector.transitive && context.satisfied_by(&self.selector.product, dep_product.type_id())  {
      // If the dep_product is an inner node in the traversal, prepend it to the list of
      // items to be merged.
      // TODO: would be nice to do this in one operation.
      let prepend = context.store_list(vec![dep_product], false);
      let mut prepended = dep_values;
      prepended.insert(0, &prepend);
      context.store_list(prepended, self.selector.transitive)
    } else {
      // Not an inner node, or not a traversal.
      context.store_list(dep_values, self.selector.transitive)
    }
  }
}

impl Step for SelectDependencies {
  fn step(&self, context: Context) -> StepFuture {
    let node = self.clone();

    context
      .get(
        // Select the product holding the dependency list.
        &Node::create(
          Selector::select(self.selector.dep_product),
          self.subject.clone(),
          self.variants.clone()
        )
      )
      .then(move |dep_product_res| {
        match dep_product_res {
          Ok(dep_product) => {
            // The product and its dependency list are available: project them.
            let deps =
              future::join_all(
                context.project_multi(&dep_product, &node.selector.field).iter()
                  .map(|dep_subject| {
                    context.get(&node.dep_node(&context, &dep_subject))
                  })
                  .collect::<Vec<_>>()
              );
            deps
              .then(move |dep_values_res| {
                // Finally, store the resulting values.
                match dep_values_res {
                  Ok(dep_values) => {
                    // TODO: cloning to go from a `SharedValue` list to a list of values...
                    // there ought to be a better way.
                    let dv: Vec<Value> = dep_values.iter().map(|v| context.clone_val(v)).collect();
                    Ok(node.store(&context, &dep_product, dv.iter().collect()))
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

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

impl Step for SelectProjection {
  fn step(&self, context: Context) -> StepFuture {
    let node = self.clone();

    context
      .get(
        // Request the product we need to compute the subject.
        &Node::create(
          Selector::select(self.selector.input_product),
          self.subject.clone(),
          self.variants.clone()
        )
      )
      .then(move |dep_product_res| {
        match dep_product_res {
          Ok(dep_product) => {
            // And then project the relevant field.
            let projected_subject =
              context.project(
                &dep_product,
                &node.selector.field,
                &node.selector.projected_subject
              );
            context
              .get(
                &Node::create(
                  Selector::select(node.selector.product),
                  context.key_for(&projected_subject),
                  node.variants.clone()
                )
              )
              .then(move |output_res| {
                // If the output product is available, return it.
                match output_res {
                  Ok(output) => Ok(context.clone_val(&output)),
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

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Snapshot {
  subject: Key,
  product: TypeConstraint,
  variants: Variants,
}

impl Snapshot {
  fn create(context: Context, path_globs: PathGlobs) -> StepFuture {
    // Recursively expand PathGlobs into PathStats.
    context
      .expand(path_globs)
      .and_then(move |path_stats| {
        // And then create a Snapshot.
        let snapshot_res =
          fs::Snapshot::create(
            &context.snapshot_root(),
            &context.build_root(),
            path_stats
          );
        match snapshot_res {
          Ok(snapshot) =>
            Ok(context.store_snapshot(&snapshot)),
          Err(err) =>
            Err(context.throw(&format!("Snapshot failed: {}", err)))
        }
      })
      .boxed()
  }
}

impl Step for Snapshot {
  fn step(&self, context: Context) -> StepFuture {
    // Compute and parse PathGlobs for the subject.
    context
      .get(
        &Node::create(
          Selector::select(context.type_path_globs().clone()),
          self.subject.clone(),
          self.variants.clone()
        )
      )
      .then(move |path_globs_res| {
        match path_globs_res {
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
        }
      })
      .boxed()
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  subject: Key,
  product: TypeConstraint,
  variants: Variants,
  selector: selectors::Task,
}

impl Step for Task {
  fn step(&self, context: Context) -> StepFuture {
    let deps =
      future::join_all(
        self.selector.clause.iter()
          .map(|selector| {
            context.get(&Node::create(selector.clone(), self.subject.clone(), self.variants.clone()))
          })
          .collect::<Vec<_>>()
      );

    let selector = self.selector.clone();
    deps
      .then(move |deps_result| {
        match deps_result {
          Ok(deps) =>
            context.invoke_runnable(
              &selector.func,
              &deps.iter().map(|v| context.clone_val(v)).collect(),
              selector.cacheable,
            ),
          Err(err) =>
            Err(context.was_optional(err, "Missing at least one input.")),
        }
      })
      .boxed()
  }
}

// TODO: Likely that these could be inline struct definitions, rather than independently
// defined structs.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Node {
  Select(Select),
  SelectLiteral(SelectLiteral),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  Snapshot(Snapshot),
  Task(Task),
}

impl Node {
  pub fn format(&self, externs: &Externs) -> String {
    match self {
      &Node::Select(_) => "Select".to_string(),
      &Node::SelectLiteral(_) => "Literal".to_string(),
      &Node::SelectDependencies(_) => "Dependencies".to_string(),
      &Node::SelectProjection(_) => "Projection".to_string(),
      &Node::Task(ref t) => format!("Task({})", externs.id_to_str(t.selector.func.0)),
      &Node::Snapshot(_) => "Snapshot".to_string(),
    }
  }

  pub fn subject(&self) -> &Key {
    match self {
      &Node::Select(ref s) => &s.subject,
      &Node::SelectLiteral(ref s) => &s.subject,
      &Node::SelectDependencies(ref s) => &s.subject,
      &Node::SelectProjection(ref s) => &s.subject,
      &Node::Task(ref t) => &t.subject,
      &Node::Snapshot(ref t) => &t.subject,
    }
  }

  pub fn product(&self) -> &TypeConstraint {
    match self {
      &Node::Select(ref s) => &s.selector.product,
      &Node::SelectLiteral(ref s) => &s.selector.product,
      &Node::SelectDependencies(ref s) => &s.selector.product,
      &Node::SelectProjection(ref s) => &s.selector.product,
      &Node::Task(ref t) => &t.selector.product,
      &Node::Snapshot(ref t) => &t.product,
    }
  }

  pub fn create(selector: Selector, subject: Key, variants: Variants) -> Node {
    match selector {
      Selector::Select(s) =>
        Node::Select(Select {
          subject: subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectLiteral(s) =>
        // NB: Intentionally ignores subject parameter to provide a literal subject.
        Node::SelectLiteral(SelectLiteral {
          subject: s.subject.clone(),
          variants: variants,
          selector: s,
        }),
      Selector::SelectDependencies(s) =>
        Node::SelectDependencies(SelectDependencies {
          subject: subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectProjection(s) =>
        Node::SelectProjection(SelectProjection {
          subject: subject,
          variants: variants,
          selector: s,
        }),
    }
  }

  pub fn step(&self, context: Context) -> StepFuture {
    // TODO: Odd place for this... could do it periodically in the background?
    maybe_drain_handles().map(|handles| {
      context.core.externs.drop_handles(handles);
    });

    match self {
      &Node::Select(ref n) => n.step(context),
      &Node::SelectDependencies(ref n) => n.step(context),
      &Node::SelectLiteral(ref n) => n.step(context),
      &Node::SelectProjection(ref n) => n.step(context),
      &Node::Task(ref n) => n.step(context),
      &Node::Snapshot(ref n) => n.step(context),
    }
  }
}
