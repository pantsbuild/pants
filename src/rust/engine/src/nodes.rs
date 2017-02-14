// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

use futures::future::{BoxFuture, Future};
use futures::future;
use futures_cpupool::CpuPool;

use core::{Function, Key, TypeConstraint, TypeId, Value, Variants};
use externs;
use graph::{EntryId, Graph};
use handles::maybe_drain_handles;
use selectors::Selector;
use selectors;
use tasks::{self, Tasks};


#[derive(Debug)]
pub struct Runnable {
  pub func: Function,
  pub args: Vec<Value>,
  pub cacheable: bool,
}

#[derive(Debug, Clone)]
pub enum Failure {
  Noop(&'static str, Option<Node>),
  Throw(Value),
}

pub type StepFuture<T> = BoxFuture<T, Failure>;

// Because multiple callers may wait on the same Node, the Future for a Node must be shareable.
pub type NodeFuture<T> = future::Shared<StepFuture<T>>;

#[derive(Clone)]
pub struct Context {
  entry_id: EntryId,
  graph: Arc<Graph>,
  tasks: Arc<Tasks>,
  pool: CpuPool,
}

impl Context {
  pub fn new(entry_id: EntryId, graph: Arc<Graph>, tasks: Arc<Tasks>, pool: CpuPool) -> Context {
    Context {
      entry_id: entry_id,
      graph: graph,
      tasks: tasks,
      pool: pool,
    }
  }

  /**
   * Create Nodes for each Task that might be able to compute the given product for the
   * given subject and variants.
   *
   * (analogous to NodeBuilder.gen_nodes)
   */
  fn gen_nodes(&self, subject: &Key, product: &TypeConstraint, variants: &Variants) -> Vec<Task> {
    self.tasks.gen_tasks(subject.type_id(), product)
      .map(|tasks| {
        tasks.iter()
          .map(|task|
            Task {
              subject: subject.clone(),
              product: product.clone(),
              variants: variants.clone(),
              task: task.clone(),
            }
          )
          .collect()
      })
      .unwrap_or_else(|| Vec::new())
  }

  /**
   * Get the future value for the given Node implementation.
   */
  fn get<N: Step>(&self, node: N) -> NodeFuture<N::Output> {
    // TODO: Odd place for this... could do it periodically in the background?
    maybe_drain_handles().map(|handles| {
      externs::drop_handles(handles);
    });

    self.graph.get(self.entry_id, self, node)
  }

  fn has_products(&self, item: &Value) -> bool {
    externs::satisfied_by(&self.tasks.type_has_products, item.type_id())
  }

  /**
   * Returns the `name` field of the given item.
   *
   * TODO: There is no check that the object _has_ a name field.
   */
  fn field_name(&self, item: &Value) -> String {
    externs::project_str(item, self.tasks.field_name.as_str())
  }

  fn field_products(&self, item: &Value) -> Vec<Value> {
    self.project_multi(item, &self.tasks.field_products)
  }

  fn key_for(&self, val: &Value) -> Key {
    externs::key_for(val)
  }

  fn val_for(&self, key: &Key) -> Value {
    externs::val_for(key)
  }

  fn clone_val(&self, val: &Value) -> Value {
    externs::clone_val(val)
  }

  /**
   * Stores a list of Keys, resulting in a Key for the list.
   */
  fn store_list(&self, items: Vec<&Value>, merge: bool) -> Value {
    externs::store_list(items, merge)
  }

  /**
   * Calls back to Python for a satisfied_by check.
   */
  fn satisfied_by(&self, constraint: &TypeConstraint, cls: &TypeId) -> bool {
    externs::satisfied_by(constraint, cls)
  }

  /**
   * Calls back to Python to project a field.
   */
  fn project(&self, item: &Value, field: &str, type_id: &TypeId) -> Value {
    externs::project(item, field, type_id)
  }

  /**
   * Calls back to Python to project a field representing a collection.
   */
  fn project_multi(&self, item: &Value, field: &str) -> Vec<Value> {
    externs::project_multi(item, field)
  }

  /**
   * Creates a Throw state with the given exception message.
   */
  fn throw(&self, msg: &str) -> Failure {
    Failure::Throw(externs::create_exception(msg))
  }

  fn invoke_runnable(&self, runnable: Runnable) -> Result<Value, Failure> {
    externs::invoke_runnable(&runnable)
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

  fn ok<O: Send + 'static>(&self, value: O) -> StepFuture<O> {
    future::ok(value).boxed()
  }

  fn err<O: Send + 'static>(&self, failure: Failure) -> StepFuture<O> {
    future::err(failure).boxed()
  }
}

pub trait ContextFactory {
  fn create(&self, entry_id: EntryId) -> Context;
}

impl ContextFactory for Context {
  /**
   * Clones this Context for a new EntryId. Because all of the members of the context
   * are Arcs (CpuPool internally), this is a shallow clone.
   *
   * TODO: Consider reducing to a single Arc to hold the shareable portion of the context.
   */
  fn create(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: entry_id,
      graph: self.graph.clone(),
      tasks: self.tasks.clone(),
      pool: self.pool.clone(),
    }
  }
}

/**
 * Defines executing a cacheable/memoizable step for the given context.
 *
 * The Output type of a Step is bounded to values that can be stored and retrieved from
 * the NodeResult enum. Due to the semantics of memoization, retrieving the typed result
 * stored inside the NodeResult requires an implementation of From<NodeResult>. But the
 * combination of bounds at usage sites mean that a failure to unwrap the result should
 * be exceedingly rare.
 */
pub trait Step: Into<Node> {
  type Output: Clone + Into<NodeResult> + TryFrom<NodeResult> + Send + 'static;

  fn step(&self, context: Context) -> StepFuture<Self::Output>;
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
  type Output = Value;

  fn step(&self, context: Context) -> StepFuture<Value> {
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
        context.gen_nodes(&self.subject, &self.selector.product, &self.variants).into_iter()
          .map(|task_node| {
            // Attempt to get the value of each task Node, but don't fail the join if one fails.
            context.get(task_node).then(|r| future::ok(r))
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

impl From<Select> for Node {
  fn from(n: Select) -> Self {
    Node::Select(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectLiteral,
}

impl Step for SelectLiteral {
  type Output = Value;

  fn step(&self, context: Context) -> StepFuture<Value> {
    context.ok(context.val_for(&self.selector.subject))
  }
}

impl From<SelectLiteral> for Node {
  fn from(n: SelectLiteral) -> Self {
    Node::SelectLiteral(n)
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

    let dep_subject_key = context.key_for(dep_subject);
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
  type Output = Value;

  fn step(&self, context: Context) -> StepFuture<Value> {
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
                context.project_multi(&dep_product, &node.selector.field).iter()
                  .map(|dep_subject| {
                    node.get_dep(&context, &dep_subject)
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

impl From<SelectDependencies> for Node {
  fn from(n: SelectDependencies) -> Self {
    Node::SelectDependencies(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

impl Step for SelectProjection {
  type Output = Value;

  fn step(&self, context: Context) -> StepFuture<Value> {
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
              context.project(
                &dep_product,
                &node.selector.field,
                &node.selector.projected_subject
              );
            context
              .get(
                Select::new(
                  node.selector.product,
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

impl From<SelectProjection> for Node {
  fn from(n: SelectProjection) -> Self {
    Node::SelectProjection(n)
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

impl Step for Task {
  type Output = Value;

  fn step(&self, context: Context) -> StepFuture<Value> {
    let deps =
      future::join_all(
        self.task.clause.iter()
          .map(|selector| self.get(&context, selector.clone()))
          .collect::<Vec<_>>()
      );

    let task = self.task.clone();
    deps
      .then(move |deps_result| {
        match deps_result {
          Ok(deps) =>
            context.invoke_runnable(
              Runnable {
                func: task.func,
                args: deps.iter().map(|v| context.clone_val(v)).collect(),
                cacheable: task.cacheable,
              }
            ),
          Err(err) =>
            Err(context.was_optional(err, "Missing at least one input.")),
        }
      })
      .boxed()
  }
}

impl From<Task> for Node {
  fn from(n: Task) -> Self {
    Node::Task(n)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Node {
  Select(Select),
  SelectLiteral(SelectLiteral),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  Task(Task),
}

impl Node {
  pub fn format(&self) -> String {
    match self {
      &Node::Select(_) => "Select".to_string(),
      &Node::SelectLiteral(_) => "Literal".to_string(),
      &Node::SelectDependencies(_) => "Dependencies".to_string(),
      &Node::SelectProjection(_) => "Projection".to_string(),
      &Node::Task(ref t) => format!("Task({})", externs::id_to_str(t.task.func.0)),
    }
  }

  pub fn subject(&self) -> &Key {
    match self {
      &Node::Select(ref s) => &s.subject,
      &Node::SelectLiteral(ref s) => &s.subject,
      &Node::SelectDependencies(ref s) => &s.subject,
      &Node::SelectProjection(ref s) => &s.subject,
      &Node::Task(ref t) => &t.subject,
    }
  }

  pub fn product(&self) -> &TypeConstraint {
    match self {
      &Node::Select(ref s) => &s.selector.product,
      &Node::SelectLiteral(ref s) => &s.selector.product,
      &Node::SelectDependencies(ref s) => &s.selector.product,
      &Node::SelectProjection(ref s) => &s.selector.product,
      &Node::Task(ref t) => &t.product,
    }
  }
}

impl Step for Node {
  type Output = NodeResult;

  fn step(&self, context: Context) -> StepFuture<NodeResult> {
    match self {
      &Node::Select(ref n) => n.step(context).map(|v| v.into()).boxed(),
      &Node::SelectDependencies(ref n) => n.step(context).map(|v| v.into()).boxed(),
      &Node::SelectLiteral(ref n) => n.step(context).map(|v| v.into()).boxed(),
      &Node::SelectProjection(ref n) => n.step(context).map(|v| v.into()).boxed(),
      &Node::Task(ref n) => n.step(context).map(|v| v.into()).boxed(),
    }
  }
}

#[derive(Clone, Debug)]
pub enum NodeResult {
  Value(Value),
}

impl NodeResult {
  pub fn clone(&self) -> NodeResult {
    match self {
      &NodeResult::Value(ref v) => NodeResult::Value(externs::clone_val(v)),
    }
  }
}

impl From<Value> for NodeResult {
  fn from(v: Value) -> Self {
    NodeResult::Value(v)
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
    }
  }
}
