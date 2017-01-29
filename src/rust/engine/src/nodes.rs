
use std::sync::Arc;

use futures::future::{BoxFuture, Future};
use futures::future;

use graph::{EntryId, GraphContext};
use core::{Field, Function, Key, TypeConstraint, TypeId, Value, Variants};
use externs::Externs;
use selectors::Selector;
use selectors;
use tasks::Tasks;


#[derive(Debug)]
pub struct Runnable {
  func: Function,
  args: Vec<Value>,
  cacheable: bool,
}

impl Runnable {
  pub fn func(&self) -> &Function {
    &self.func
  }

  pub fn args(&self) -> &Vec<Value> {
    &self.args
  }

  pub fn cacheable(&self) -> bool {
    self.cacheable
  }
}

#[derive(Debug)]
pub enum State {
  Waiting(Vec<Node>),
  Complete(Complete),
  Runnable(Runnable),
}

#[derive(Debug)]
pub enum Complete {
  Noop(&'static str, Option<Node>),
  Return(Value),
  Throw(Value),
}

#[derive(Debug)]
pub enum Failure {
  Noop(&'static str, Option<Node>),
  Throw(Value),
}

// Individual Steps will be pulled by the Scheduler's pool, and thus need not be shareable.
pub type StepFuture = BoxFuture<Value, Failure>;

// Because multiple callers may wait on the same Node, the Future for a Node must be shareable.
pub type NodeFuture = future::Shared<StepFuture>;

#[derive(Clone)]
pub struct StepContext {
  entry_id: EntryId,
  graph: GraphContext,
  tasks: Arc<Tasks>,
}

impl StepContext {
  /**
   * Create Nodes for each Task that might be able to compute the given product for the
   * given subject and variants.
   *
   * (analogous to NodeBuilder.gen_nodes)
   */
  fn gen_nodes(&self, subject: &Key, product: &TypeConstraint, variants: &Variants) -> Vec<Node> {
    self.tasks.gen_tasks(subject.type_id(), product)
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

  /**
   * Get the future value for the given Node.
   */
  fn get(&self, node: &Node) -> NodeFuture {
    self.graph.get(node)
  }

  fn has_products(&self, item: &Value) -> bool {
    self.tasks.externs.satisfied_by(&self.tasks.type_has_products, item.type_id())
  }

  /**
   * Returns the `name` field of the given item.
   *
   * TODO: There are at least two hacks here. Because we don't have access to the appropriate
   * `str` type, we just assume that it has the same type as the name of the field. And more
   * importantly, there is no check that the object _has_ a name field.
   */
  fn field_name(&self, item: &Value) -> String {
    let name_val =
      self.project(
        item,
        &self.tasks.field_name,
        self.tasks.field_name.0.type_id()
      );
    self.tasks.externs.val_to_str(&name_val)
  }

  fn field_products(&self, item: &Value) -> Vec<Value> {
    self.project_multi(item, &self.tasks.field_products)
  }

  fn key_for(&self, val: &Value) -> Key {
    self.tasks.externs.key_for(val)
  }

  fn val_for(&self, key: &Key) -> Value {
    self.tasks.externs.val_for(key)
  }

  fn clone_val(&self, val: &Value) -> Value {
    self.tasks.externs.clone_val(val)
  }

  /**
   * Stores a list of Keys, resulting in a Key for the list.
   */
  fn store_list(&self, items: Vec<&Value>, merge: bool) -> Value {
    self.tasks.externs.store_list(items, merge)
  }

  /**
   * Calls back to Python for a satisfied_by check.
   */
  fn satisfied_by(&self, constraint: &TypeConstraint, cls: &TypeId) -> bool {
    self.tasks.externs.satisfied_by(constraint, cls)
  }

  /**
   * Calls back to Python to project a field.
   */
  fn project(&self, item: &Value, field: &Field, type_id: &TypeId) -> Value {
    self.tasks.externs.project(item, field, type_id)
  }

  /**
   * Calls back to Python to project a field representing a collection.
   */
  fn project_multi(&self, item: &Value, field: &Field) -> Vec<Value> {
    self.tasks.externs.project_multi(item, field)
  }

  /**
   * Creates a Throw state with the given exception message.
   */
  fn throw(&self, msg: &str) -> Failure {
    Failure::Throw(self.tasks.externs.create_exception(msg))
  }

  fn invoke_runnable(&self, runnable: Runnable) -> Result<Value, Failure> {
    self.tasks.externs.invoke_runnable(&runnable)
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
}

/**
 * Defines executing a single step for the given context.
 */
trait Step {
  fn step(&self, context: StepContext) -> StepFuture;

  fn ok(&self, value: Value) -> StepFuture {
    future::ok(value).boxed()
  }

  fn err(&self, failure: Failure) -> StepFuture {
    future::err(failure).boxed()
  }
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
    context: &StepContext,
    candidate: &'a Value,
    variant_value: Option<String>
  ) -> bool {
    if !context.satisfied_by(&self.selector.product, candidate.type_id()) {
      return false;
    }
    return match variant_value {
      Some(vv) if context.field_name(candidate) != *vv =>
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
    context: &StepContext,
    candidate: Value,
    variant_value: Option<String>
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
    context: StepContext,
    results: Vec<Result<Value, Failure>>,
    variant_value: Option<String>,
  ) -> Result<Value, Failure> {
    let mut matches = Vec::new();
    for result in results {
      match result {
        Ok(ref value) => {
          if let Some(v) = self.select_literal(&context, context.clone_val(value), variant_value) {
            matches.push(v);
          }
        },
        Err(Failure::Noop(_, _)) =>
          continue,
        Err(Failure::Throw(ref msg)) =>
          return Err(Failure::Throw(context.clone_val(msg))),
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
  fn step(&self, context: StepContext) -> StepFuture {
    // TODO add back support for variants https://github.com/pantsbuild/pants/issues/4020

    // If there is a variant_key, see whether it has been configured; if not, no match.
    let variant_value: Option<String> =
      match self.selector.variant_key {
        Some(ref variant_key) => {
          let variant_value = self.variants.find(variant_key);
          if variant_value.is_none() {
            return self.err(
              Failure::Noop("A matching variant key was not configured in variants.", None)
            );
          }
          variant_value.map(|v| v.to_string())
        },
        None => None,
      };

    // If the Subject "is a" or "has a" Product, then we're done.
    if let Some(literal_value) = self.select_literal(&context, context.val_for(&self.subject), variant_value) {
      return self.ok(literal_value);
    }

    // Else, attempt to use the configured tasks to compute the value.
    let deps_future =
      future::join_all(
        context.gen_nodes(&self.subject, self.product(), &self.variants).iter()
          .map(|task_node| {
            // Attempt to get the value of each task Node, but don't fail the join if one fails.
            context.get(&task_node).then(|r| future::ok(r))
          })
      );

    let variant_value = variant_value.map(|s| s.to_string());
    let node = self.clone();
    deps_future
      .and_then(move |dep_results| {
        future::result(node.choose_task_result(context, dep_results, variant_value))
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
  fn step(&self, context: StepContext) -> StepFuture {
    self.ok(context.val_for(&self.selector.subject))
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
  fn dep_node(&self, context: &StepContext, dep_subject: &Value) -> Node {
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

  fn store(&self, context: &StepContext, dep_product: &Value, dep_values: Vec<&Value>) -> Value {
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
  fn step(&self, context: StepContext) -> StepFuture {
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
              );
            deps
              .then(move |dep_values_res| {
                // Finally, store the resulting values.
                match dep_values_res {
                  Ok(dep_values) =>
                    Ok(
                      node.store(
                        &context,
                        &dep_product,
                        dep_values.into_iter().map(|v| &*v).collect()
                      )
                    ),
                  Err(failure) =>
                    Err(context.was_required(failure)),
                }
              })
              .boxed()
          },
          Err(failure) =>
            node.err(context.was_optional(failure, "No source of input product.")),
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
  fn step(&self, context: StepContext) -> StepFuture {
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
            node.err(context.was_optional(failure, "No source of input product.")),
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
  fn step(&self, context: StepContext) -> StepFuture {
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
              Runnable {
                func: selector.func,
                args: deps.iter().map(|v| context.clone_val(v)).collect(),
                cacheable: selector.cacheable,
              }
            ),
          Err(err) =>
            Err(context.was_optional(err, "Missing at least one input.")),
        }
      })
      .boxed()
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
  pub fn format(&self, externs: &Externs) -> String {
    match self {
      &Node::Select(_) => "Select".to_string(),
      &Node::SelectLiteral(_) => "Literal".to_string(),
      &Node::SelectDependencies(_) => "Dependencies".to_string(),
      &Node::SelectProjection(_) => "Projection".to_string(),
      &Node::Task(ref t) => format!("Task({})", externs.id_to_str(t.selector.func.0)),
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
      &Node::Task(ref t) => &t.selector.product,
    }
  }

  pub fn selector(&self) -> Selector {
    match self {
      &Node::Select(ref s) => Selector::Select(s.selector.clone()),
      &Node::SelectLiteral(ref s) => Selector::SelectLiteral(s.selector.clone()),
      &Node::SelectDependencies(ref s) => Selector::SelectDependencies(s.selector.clone()),
      &Node::SelectProjection(ref s) => Selector::SelectProjection(s.selector.clone()),
      &Node::Task(ref t) => Selector::Task(t.selector.clone()),
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
      Selector::Task(t) =>
        Node::Task(Task {
          subject: subject,
          product: t.product,
          variants: variants,
          selector: t,
        }),
    }
  }

  pub fn step(&self, entry_id: EntryId, graph: GraphContext, tasks: Arc<Tasks>) -> StepFuture {
    let context =
      StepContext {
        entry_id: entry_id,
        graph: graph,
        tasks: tasks,
      };
    match self {
      &Node::Select(ref n) => n.step(context),
      &Node::SelectDependencies(ref n) => n.step(context),
      &Node::SelectLiteral(ref n) => n.step(context),
      &Node::SelectProjection(ref n) => n.step(context),
      &Node::Task(ref n) => n.step(context),
    }
  }
}
