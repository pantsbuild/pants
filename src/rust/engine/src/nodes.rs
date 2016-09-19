use std::hash::Hash;

use graph::{Entry, Graph};
use core::{Field, Function, Key, TypeId, Variants};
use externs::ToStrFunction;
use selectors::Selector;
use selectors;
use tasks::Tasks;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum StagedArg<T> {
  Key(Key),
  Promise(T),
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Staged<T> {
  pub func: Function,
  pub args: Vec<StagedArg<T>>,
  pub cacheable: bool,
}

impl<T: Clone + Eq + Hash> Staged<T> {
  /**
   * Return all dependencies declared by this state.
   */
  pub fn dependencies(&self) -> Vec<T> {
    self.args.iter()
      .filter_map(|arg|
        match arg {
          &StagedArg::Promise(ref t) => Some(t.clone()),
          &StagedArg::Key(_) => None,
        }
      )
      .collect()
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum State<T> {
  Waiting(Vec<T>),
  Complete(Complete),
  Staged(Staged<T>),
}

impl<T: Clone + Eq + Hash> State<T> {
  pub fn empty_waiting() -> State<T> {
    State::Waiting(Vec::new())
  }

  /**
   * Return all dependencies declared by this state.
   */
  pub fn dependencies(&self) -> Option<Vec<T>> {
    match self {
      &State::Complete(_) => None,
      &State::Staged(ref s) => Some(s.dependencies()),
      &State::Waiting(ref w) if w.is_empty() => None,
      &State::Waiting(ref w) => Some(w.iter().map(|s| s.clone()).collect()),
    }
  }

  /**
   * Converts a State of type T to a State of type O.
   */
  pub fn map<O,F>(self, mut conversion: F) -> State<O>
      where F: FnMut(T)->O {
    match self {
      State::Complete(c) => State::Complete(c),
      State::Staged(s) =>
        State::Staged(
          Staged {
            func: s.func,
            args:
              s.args.into_iter()
                .map(|a| {
                  match a {
                    StagedArg::Key(k) => StagedArg::Key(k),
                    StagedArg::Promise(p) => StagedArg::Promise(conversion(p)),
                  }
                })
                .collect(),
            cacheable: s.cacheable
          }
        ),
      State::Waiting(w) => State::Waiting(w.into_iter().map(conversion).collect()),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Complete {
  Noop(&'static str, Option<Node>),
  Return(Key),
  Throw(String),
}

static CYCLIC: Complete = Complete::Noop("Dep would be cyclic.", None);

pub struct StepContext<'g,'t> {
  entry: &'g Entry,
  graph: &'g Graph,
  tasks: &'t Tasks,
  to_str: &'t ToStrFunction,
}

impl<'g,'t> StepContext<'g,'t> {
  /**
   * Create Nodes for each Task that might be able to compute the given product for the
   * given subject and variants.
   *
   * (analogous to NodeBuilder.gen_nodes)
   */
  fn gen_nodes(&self, subject: &Key, product: &TypeId, variants: &Variants) -> Vec<Node> {
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

  fn get(&self, node: &Node) -> Option<&Complete> {
    self.graph.entry(node).and_then(|dep_entry| {
      // The entry exists. If it's a declared dep, return it immediately.
      if self.entry.dependencies().contains(&dep_entry.id()) {
        // Declared.
        match dep_entry.state() {
          &State::Complete(ref c) => Some(c),
          _ => None,
        }
      } else if self.entry.cyclic_dependencies().contains(&dep_entry.id()) {
        // Declared, but cyclic.
        Some(&CYCLIC)
      } else {
        // Undeclared. In theory we could still immediately return the dep here, but unfortunately
        // that occasionally allows Nodes to finish executing before all of their declared deps are
        // available.
        None
      }
    })
  }

  fn type_address(&self) -> &TypeId {
    &self.tasks.type_address
  }

  fn type_has_variants(&self) -> &TypeId {
    &self.tasks.type_has_variants
  }

  fn has_products(&self, item: &Key) -> bool {
    self.isinstance(item, &self.tasks.type_has_products)
  }

  fn field_name(&self, item: &Key) -> Key {
    panic!("TODO: Not implemented");
    //self.project(item, &self.tasks.field_name)
  }

  fn field_variants(&self, item: &Key) -> Key {
    panic!("TODO: Not implemented");
    //self.project(item, &self.tasks.field_variants)
  }

  fn field_products(&self, item: &Key) -> Vec<Key> {
    panic!("TODO: Not implemented");
    //self.project_multi(item, &self.tasks.field_products)
  }

  /**
   * Stores a list of Keys, resulting in a Key for the list.
   */
  fn store_list(&self, items: Vec<&Key>, merge: bool) -> Key {
    (self.tasks.store_list).call(items, merge)
  }

  /**
   * Calls back to Python for an issubclass check.
   */
  fn isinstance(&self, item: &Key, superclass: &TypeId) -> bool {
    if item.type_id() == superclass {
      true
    } else {
      (self.tasks.issubclass).call(item.type_id(), superclass)
    }
  }

  /**
   * Calls back to Python to project a field.
   */
  fn project(&self, item: &Key, field: &Field, type_id: &TypeId) -> Key {
    (self.tasks.project).call(item, field, type_id)
  }

  /**
   * Calls back to Python to project a field representing a collection.
   */
  fn project_multi(&self, item: &Key, field: &Field) -> Vec<Key> {
    (self.tasks.project_multi).call(item, field)
  }

  fn to_str(&self) -> &ToStrFunction {
    self.to_str
  }
}

/**
 * Defines executing a single step for the given context.
 */
trait Step {
  fn step(&self, context: StepContext) -> State<Node>;
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
  fn product(&self) -> &TypeId {
    &self.selector.product
  }

  fn select_literal_single<'a>(
    &self,
    context: &StepContext,
    candidate: &'a Key,
    variant_value: Option<&Key>
  ) -> Option<&'a Key> {
    if !context.isinstance(candidate, &self.selector.product) {
      return None;
    }
    match variant_value {
      Some(vv) if context.field_name(candidate) != *vv =>
        // There is a variant value, and it doesn't match.
        return None,
      _ =>
        return Some(candidate),
    }
  }

  /**
   * Looks for has-a or is-a relationships between the given value and the requested product.
   *
   * Returns the resulting product value, or None if no match was made.
   */
  fn select_literal(
    &self,
    context: &StepContext,
    candidate: &Key,
    variant_value: Option<&Key>
  ) -> Option<Key> {
    // Check whether the subject is-a instance of the product.
    if let Some(&candidate) = self.select_literal_single(context, candidate, variant_value) {
      return Some(candidate)
    }

    // Else, check whether it has-a instance of the product.
    // TODO: returning only the first literal configuration of a given type/variant. Need to
    // define mergeability for products.
    if context.has_products(candidate) {
      for child in context.field_products(candidate) {
        if let Some(&child) = self.select_literal_single(context, &child, variant_value) {
          return Some(child);
        }
      }
    }
    return None;
  }
}

impl Step for Select {
  fn step(&self, context: StepContext) -> State<Node> {
    // Request default Variants for the subject, so that if there are any we can propagate
    // them to task nodes.
    let variants =
      if self.subject.type_id() == context.type_address() &&
        self.product() != context.type_has_variants() {
        let variants_node =
          Node::create(
            Selector::select(context.type_has_variants().clone()),
            self.subject.clone(),
            self.variants.clone(),
          );
        match context.get(&variants_node) {
          Some(&Complete::Return(_)) =>
            panic!("TODO: merging variants is not yet implemented"),
          Some(&Complete::Noop(_, _)) =>
            &self.variants,
          Some(&Complete::Throw(ref msg)) =>
            return State::Complete(Complete::Throw(msg.clone())),
          None =>
            return State::Waiting(vec![variants_node]),
        }
      } else {
        &self.variants
      };

    // If there is a variant_key, see whether it has been configured; if not, no match.
    let variant_value: Option<&Key> =
      match self.selector.variant_key {
        Some(ref variant_key) => {
          let variant_value: Option<&Key> =
            variants.iter()
              .find(|&&(ref k, _)| k == variant_key)
              .map(|&(_, ref v)| v);
          if variant_value.is_none() {
            return State::Complete(
              Complete::Noop("A matching variant key was not configured in variants.", None)
            )
          }
          variant_value
        },
        None => None,
      };

    // If the Subject "is a" or "has a" Product, then we're done.
    if let Some(literal_value) = self.select_literal(&context, &self.subject, variant_value) {
      return State::Complete(Complete::Return(literal_value));
    }

    // Else, attempt to use a configured task to compute the value.
    let mut dependencies = Vec::new();
    let mut matches: Vec<Key> = Vec::new();
    for dep_node in context.gen_nodes(&self.subject, self.product(), &self.variants) {
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) => {
          if let Some(v) = self.select_literal(&context, value, variant_value) {
            matches.push(v);
          }
        },
        Some(&Complete::Noop(_, _)) =>
          continue,
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(msg.clone())),
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
        Complete::Throw(
          format!("Conflicting values produced for subject and type.")
        )
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
  fn step(&self, _: StepContext) -> State<Node> {
    State::Complete(Complete::Return(self.selector.subject))
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
  fn dep_product(&self, context: &StepContext) -> Result<Key, State<Node>> {
    // Request the product we need in order to request dependencies.
    let dep_product_node =
      Node::create(
        Selector::select(self.selector.dep_product),
        self.subject,
        self.variants.clone()
      );
    match context.get(&dep_product_node) {
      Some(&Complete::Return(ref value)) =>
        Ok(value.clone()),
      Some(&Complete::Noop(_, _)) =>
        Err(
          State::Complete(
          Complete::Noop("Could not compute {} to determine deps.", Some(dep_product_node))
          )
        ),
      Some(&Complete::Throw(ref msg)) =>
        Err(State::Complete(Complete::Throw(msg.clone()))),
      None =>
        Err(State::Waiting(vec![dep_product_node])),
    }
  }

  fn dep_node(&self, dep_subject: Key) -> Node {
    if self.selector.traversal {
      // After the root has been expanded, a traversal continues with dep_product == product.
      let mut selector = self.selector.clone();
      selector.dep_product = selector.product;
      Node::create(
        Selector::SelectDependencies(selector),
        dep_subject,
        self.variants.clone()
      )
    } else {
      Node::create(Selector::select(self.selector.product), dep_subject, self.variants.clone())
    }
  }

  fn store(&self, context: &StepContext, dep_product: &Key, dep_values: Vec<&Key>) -> Key {
    if self.selector.traversal && dep_product.type_id() == &self.selector.product {
      // If the dep_product is an inner node in the traversal, prepend it to the list of
      // items to be merged.
      // TODO: would be nice to do this in one operation.
      let prepend = context.store_list(vec![dep_product], false);
      let mut prepended = dep_values;
      prepended.insert(0, &prepend);
      context.store_list(prepended, self.selector.traversal)
    } else {
      // Not an inner node, or not a traversal.
      context.store_list(dep_values, self.selector.traversal)
    }
  }
}

impl Step for SelectDependencies {
  fn step(&self, context: StepContext) -> State<Node> {
    // Select the product holding the dependency list.
    let dep_product =
      match self.dep_product(&context) {
        Ok(dep_product) => dep_product,
        Err(state) => return state,
      };

    // The product and its dependency list are available.
    let mut dependencies = Vec::new();
    let mut dep_values: Vec<&Key> = Vec::new();
    for dep_subject in context.project_multi(&dep_product, &self.selector.field) {
      let dep_node = self.dep_node(dep_subject);
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(&value),
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Throw(
              format!("No source of explicit dep {}", dep_node.format(context.to_str()))
            )
          ),
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(msg.clone())),
        None =>
          dependencies.push(dep_node),
      }
    }

    if dependencies.len() > 0 {
      State::Waiting(dependencies)
    } else {
      State::Complete(Complete::Return(self.store(&context, &dep_product, dep_values)))
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

impl Step for SelectProjection {
  fn step(&self, context: StepContext) -> State<Node> {
    // Request the product we need to compute the subject.
    let input_node =
      Node::create(
        Selector::select(self.selector.input_product),
        self.subject,
        self.variants.clone()
      );
    let dep_product =
      match context.get(&input_node) {
        Some(&Complete::Return(ref value)) =>
          value,
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Noop("Could not compute {} to project its field.", Some(input_node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(msg.clone())),
        None =>
          return State::Waiting(vec![input_node]),
      };

    // The input product is available: use it to construct the new Subject.
    let projected_subject =
      context.project(
        dep_product,
        &self.selector.field,
        &self.selector.projected_subject
      );

    // When the output product is available, return it.
    let output_node =
      Node::create(
        Selector::select(self.selector.product),
        projected_subject,
        self.variants.clone()
      );
    match context.get(&output_node) {
      Some(&Complete::Return(value)) =>
        return State::Complete(Complete::Return(value)),
      Some(&Complete::Noop(_, _)) =>
        return State::Complete(
          Complete::Throw(
            format!("No source of projected dependency {}", output_node.format(context.to_str()))
          )
        ),
      Some(&Complete::Throw(ref msg)) =>
        // NB: propagate thrown exception directly.
        return State::Complete(Complete::Throw(msg.clone())),
      None =>
        return State::Waiting(vec![output_node]),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  subject: Key,
  product: TypeId,
  variants: Variants,
  selector: selectors::Task,
}

impl Step for Task {
  fn step(&self, _: StepContext) -> State<Node> {
    // Stage the Node to run immediately.
    State::Staged(Staged {
      func: self.selector.func,
      args:
        self.selector.clause.iter()
          .map(|selector|
            StagedArg::Promise(
              Node::create(
                selector.clone(),
                self.subject,
                self.variants.clone()
              )
            )
          )
          .collect(),
      cacheable: self.selector.cacheable,
    })
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
  pub fn format(&self, to_str: &ToStrFunction) -> String {
    match self {
      &Node::Select(_) => "Select".to_string(),
      &Node::SelectLiteral(_) => "Literal".to_string(),
      &Node::SelectDependencies(_) => "Dependencies".to_string(),
      &Node::SelectProjection(_) => "Projection".to_string(),
      &Node::Task(ref t) => format!("Task({})", to_str.call(&t.selector.func)),
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

  pub fn product(&self) -> &TypeId {
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
          subject: s.subject,
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

  pub fn step(&self, entry: &Entry, graph: &Graph, tasks: &Tasks, to_str: &ToStrFunction) -> State<Node> {
    let context =
      StepContext {
        entry: entry,
        graph: graph,
        tasks: tasks,
        to_str: to_str
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
