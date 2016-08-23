use std::collections::HashMap;
use std::rc::Rc;

use core::{Field, Function, Key, TypeId, Variants};
use selectors;
use selectors::Selector;
use tasks::Tasks;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Runnable {
  func: Function,
  args: Vec<Key>,
  cacheable: bool,
}

impl Runnable {
  pub fn func(&self) -> &Function {
    &self.func
  }

  pub fn args(&self) -> &Vec<Key> {
    &self.args
  }

  pub fn cacheable(&self) -> bool {
    self.cacheable
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum State {
  Waiting(Vec<Node>),
  Complete(Complete),
  Runnable(Runnable),
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Complete {
  Noop(String),
  Return(Key),
  Throw(String),
}

pub struct StepContext<'g,'t> {
  deps: HashMap<&'g Node, &'g Complete>,
  tasks: &'t Tasks,
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
                func: task.func().clone(),
                clause: task.input_clause().clone(),
                cacheable: task.cacheable(),
              }
            )
          )
          .collect()
      })
      .unwrap_or_else(|| Vec::new())
  }

  fn get(&self, node: &Node) -> Option<&Complete> {
    self.deps.get(node).map(|c| *c)
  }

  fn type_address(&self) -> &TypeId {
    self.tasks.type_address()
  }

  fn type_has_variants(&self) -> &TypeId {
    self.tasks.type_has_variants()
  }

  fn has_products(&self, item: &Key) -> bool {
    self.isinstance(item, self.tasks.type_has_products())
  }

  fn field_name(&self, item: &Key) -> Key {
    self.project(item, self.tasks.field_name())
  }

  fn field_variants(&self, item: &Key) -> Key {
    self.project(item, self.tasks.field_variants())
  }

  fn field_products(&self, item: &Key) -> Vec<Key> {
    self.project_multi(item, self.tasks.field_products())
  }

  /**
   * Stores a list of Keys, resulting in a Key for the list.
   */
  fn store_list(&self, items: Vec<&Key>) -> Key {
    self.tasks.store_list(items)
  }

  /**
   * Calls back to Python for an isinstance check.
   */
  fn isinstance(&self, item: &Key, superclass: &TypeId) -> bool {
    if item.type_id() == superclass {
      true
    } else {
      self.tasks.isinstance(item, superclass)
    }
  }

  /**
   * Calls back to Python to project a field.
   */
  fn project(&self, item: &Key, field: &Field) -> Key {
    panic!("TODO: not implemented!");
  }

  /**
   * Calls back to Python to project a field representing a collection.
   */
  fn project_multi(&self, item: &Key, field: &Field) -> Vec<Key> {
    panic!("TODO: not implemented!");
  }
}

/**
 * Defines executing a single step for the given context.
 */
trait Step {
  fn step(&self, context: StepContext) -> State;
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
  fn step(&self, context: StepContext) -> State {
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
          Some(&Complete::Return(ref value)) =>
            panic!("TODO: merging variants is not yet implemented"),
          Some(&Complete::Noop(_)) =>
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
              Complete::Noop(
                format!("Variant key {:?} was not configured in variants.", self.selector.variant_key)
              )
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
    let mut matches: Vec<&Key> = Vec::new();
    for dep_node in context.gen_nodes(&self.subject, self.product(), &self.variants) {
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          matches.push(&value),
        Some(&Complete::Noop(_)) =>
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
        Complete::Throw(format!("Conflicting values produced for this subject and type: {:?}", matches))
      );
    }

    match matches.pop() {
      Some(&matched) =>
        // Statically completed!
        State::Complete(Complete::Return(matched)),
      None =>
        State::Complete(
          Complete::Noop(format!("No source of product {:?} for {:?}.", self.product(), self.subject))
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
  fn step(&self, _: StepContext) -> State {
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
  fn product(&self) -> &TypeId {
    &self.selector.product
  }
}

impl Step for SelectDependencies {
  fn step(&self, context: StepContext) -> State {
    // Request the product we need in order to request dependencies.
    let dep_product_node =
      Node::create(
        Selector::select(self.selector.dep_product),
        self.subject,
        self.variants.clone()
      );
    let dep_product_state =
      match context.get(&dep_product_node) {
        Some(&Complete::Return(ref value)) =>
          value,
        Some(&Complete::Noop(_)) =>
          return State::Complete(
            Complete::Noop(format!("Could not compute {:?} to determine deps.", dep_product_node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(msg.clone())),
        None =>
          return State::Waiting(vec![dep_product_node]),
      };

    // The product and its dependency list are available.
    let mut dependencies = Vec::new();
    let mut dep_values: Vec<&Key> = Vec::new();
    for dep_node in context.gen_nodes(&self.subject, self.product(), &self.variants) {
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(&value),
        Some(&Complete::Noop(_)) =>
          continue,
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
      State::Complete(Complete::Return(context.store_list(dep_values)))
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
  fn step(&self, context: StepContext) -> State {
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
        Some(&Complete::Noop(_)) =>
          return State::Complete(
            Complete::Noop(format!("Could not compute {:?} to project its field.", input_node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(msg.clone())),
        None =>
          return State::Waiting(vec![input_node]),
      };

    // The input product is available: use it to construct the new Subject.
    let projected_subject = context.project(dep_product, &self.selector.field);

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
      Some(&Complete::Noop(_)) =>
        return State::Complete(
          Complete::Throw(format!("No source of projected dependency {:?}", output_node))
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
  func: Function,
  clause: Vec<selectors::Selector>,
  cacheable: bool,
}

impl Step for Task {
  fn step(&self, context: StepContext) -> State {
    // Compute dependencies for the Node, or determine whether it is a Noop.
    let mut dependencies = Vec::new();
    let mut dep_values: Vec<&Key> = Vec::new();
    for selector in &self.clause {
      let dep_node =
        Node::create(
          selector.clone(),
          self.subject,
          self.variants.clone()
        );
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(&value),
        Some(&Complete::Noop(_)) =>
          return State::Complete(
            Complete::Noop(format!("Was missing (at least) input for {:?}.", selector))
          ),
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(msg.clone())),
        None =>
          dependencies.push(dep_node),
      }
    }

    if !dependencies.is_empty() {
      // A clause was still waiting on dependencies.
      State::Waiting(dependencies)
    } else {
      // Ready to run!
      State::Runnable(Runnable {
        func: self.func,
        args: dep_values.into_iter().map(|&d| d).collect(),
        cacheable: self.cacheable,
      })
    }
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
    }
  }

  pub fn step(&self, deps: HashMap<&Node, &Complete>, tasks: &Tasks) -> State {
    let context =
      StepContext {
        deps: deps,
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
