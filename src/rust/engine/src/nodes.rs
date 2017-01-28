
use std::sync::Arc;

use futures::future::Future;
use futures::future;
use futures_cpupool::CpuPool;

use graph::{EntryId, Graph};
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

// TODO: Naming.
type CompleteFuture = Future<Item=Value, Error=Failure>;

#[derive(Clone)]
pub struct StepContext {
  entry_id: EntryId,
  graph: Arc<Graph>,
  tasks: Arc<Tasks>,
  pool: CpuPool,
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
   * TODO: switch from reference to value.
   */
  fn get(&self, node: &Node) -> Box<CompleteFuture> {
    self.graph.entry(node).and_then(|dep_entry| {
      // The entry exists. If it's a declared dep, return it immediately.
      let entry = self.graph.entry_for_id(self.entry_id);
      if entry.dependencies().contains(&dep_entry.id()) {
        dep_entry.state()
      } else if entry.cyclic_dependencies().contains(&dep_entry.id()) {
        // Declared, but cyclic.
        Some(self.graph.cyclic_singleton())
      } else {
        // Undeclared. In theory we could still immediately return the dep here, but unfortunately
        // that occasionally allows Nodes to finish executing before all of their declared deps are
        // available.
        None
      }
    })
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
  fn throw(&self, msg: String) -> Complete {
    Complete::Throw(self.tasks.externs.create_exception(msg))
  }

  fn invoke_runnable(&self, runnable: Runnable) -> Box<CompleteFuture> {
    Box::new(
      self.pool.spawn_fn(|| {
        self.tasks.externs.invoke_runnable(runnable)
      })
    )
  }
}

/**
 * Defines executing a single step for the given context.
 */
trait Step {
  fn step(&self, context: StepContext) -> Box<CompleteFuture>;

  fn ok(&self, complete: Complete) -> Box<CompleteFuture> {
    Box::new(future::ok(complete))
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
    variant_value: Option<&str>
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
    variant_value: Option<&str>
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
}

impl Step for Select {
  fn step(&self, context: StepContext) -> Box<CompleteFuture> {
    // TODO add back support for variants https://github.com/pantsbuild/pants/issues/4020
    let variants = &self.variants;

    // If there is a variant_key, see whether it has been configured; if not, no match.
    let variant_value: Option<&str> =
      match self.selector.variant_key {
        Some(ref variant_key) => {
          let variant_value = variants.find(variant_key);
          if variant_value.is_none() {
            return self.ok(
              Complete::Noop("A matching variant key was not configured in variants.", None)
            );
          }
          variant_value
        },
        None => None,
      };

    // If the Subject "is a" or "has a" Product, then we're done.
    if let Some(literal_value) = self.select_literal(&context, context.val_for(&self.subject), variant_value) {
      return self.ok(Complete::Return(literal_value));
    }

    // Else, attempt to use a configured task to compute the value.
    let mut dependencies = Vec::new();
    let mut matches: Vec<Value> = Vec::new();
    for dep_node in context.gen_nodes(&self.subject, self.product(), &self.variants) {
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) => {
          if let Some(v) = self.select_literal(&context, context.clone_val(value), variant_value) {
            matches.push(v);
          }
        },
        Some(&Complete::Noop(_, _)) =>
          continue,
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(context.clone_val(msg))),
        None =>
          dependencies.push(dep_node),
      }
    }

    // If any dependencies were unavailable, wait for them; otherwise, determine whether
    // a value was successfully selected.
    if !dependencies.is_empty() {
      // A dependency has not run yet.
      return State::Waiting(dependencies);
    } else if matches.len() > 1 {
      // TODO: Multiple successful tasks are not currently supported. We should allow for this
      // by adding support for "mergeable" products. see:
      //   https://github.com/pantsbuild/pants/issues/2526
      return State::Complete(
        context.throw(format!("Conflicting values produced for subject and type."))
      );
    }

    match matches.pop() {
      Some(matched) =>
        // Statically completed!
        State::Complete(Complete::Return(matched)),
      None =>
        State::Complete(
          Complete::Noop("No task was available to compute the value.", None)
        ),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectLiteral,
}

impl Step for SelectLiteral {
  fn step(&self, context: StepContext) -> Box<CompleteFuture> {
    State::Complete(Complete::Return(context.val_for(&self.selector.subject)))
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
  fn step(&self, context: StepContext) -> Box<CompleteFuture> {
    let node = self.clone();

    Box::new(
      context
        .get(
          // Select the product holding the dependency list.
          &Node::create(
            Selector::select(self.selector.dep_product),
            self.subject.clone(),
            self.variants.clone()
          )
        )
        .and_then(move |dep_product| {
          // The product and its dependency list are available: project them.
          let deps =
            future::join_all(
              context.project_multi(&dep_product, &node.selector.field).iter()
                .map(|dep_subject| node.dep_node(&context, &dep_subject))
                .collect()
            );
          deps.map(move |dep_values| {
            (node, context, dep_product, dep_values)
          })
        })
        .map(|(node, context, dep_product, dep_values)| {
          // Finally, store the resulting values.
          node.store(&context, &dep_product, dep_values)
        })
    )
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

impl Step for SelectProjection {
  fn step(&self, context: StepContext) -> Box<CompleteFuture> {
    let node = self.clone();

    Box::new(
      context
        .get(
          // Request the product we need to compute the subject.
          &Node::create(
            Selector::select(self.selector.input_product),
            self.subject.clone(),
            self.variants.clone()
          )
        )
        .map(move |dep_product| {
          // And then project the relevant field.
          let projected =
            context.project(
              &dep_product,
              &node.selector.field,
              &node.selector.projected_subject
            );
          (context, node, projected)
        })
        .and_then(|(context, node, projected_subject)| {
          // When the output product is available, return it.
          context.get(
            &Node::create(
              Selector::select(selector.product),
              context.key_for(&projected_subject),
              node.variants.clone()
            )
          )
        })
    )
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
  fn step(&self, context: StepContext) -> Box<CompleteFuture> {
    let deps =
      future::join_all(
        &self.selector.clause.iter()
          .map(|selector| {
            context.get(&Node::create(selector.clone(), self.subject.clone(), self.variants.clone()))
          })
          .collect()
      );

    let selector = self.selector.clone();
    Box::new(
      deps.and_then(move |deps| {
        context.invoke_runnable(
          Runnable {
            func: selector.func,
            args: deps.iter().map(|v| context.clone_val(v)).collect(),
            cacheable: selector.cacheable,
          }
        )
      })
    )
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

  pub fn step(&self, entry_id: EntryId, graph: Arc<Graph>, tasks: Arc<Tasks>, pool: CpuPool) -> Box<CompleteFuture> {
    let context =
      StepContext {
        entry_id: entry_id,
        graph: graph,
        tasks: tasks,
        pool: pool,
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
