use graph::GraphContext;
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
  Waiting,
  Complete(Complete),
  Runnable(Runnable),
}

#[derive(Debug)]
pub enum Complete {
  Noop(&'static str, Option<Node>),
  Return(Value),
  Throw(Value),
}

pub struct StepContext<'g, 't, 'e> {
  graph: &'g mut GraphContext<'g>,
  tasks: &'t Tasks,
  externs: &'e Externs,
}

impl<'g, 't, 'e> StepContext<'g, 't, 'e> {
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

  fn has_products(&self, item: &Value) -> bool {
    self.externs.satisfied_by(&self.tasks.type_has_products, item.type_id())
  }

  fn key_for(&self, val: &Value) -> Key {
    self.externs.key_for(val)
  }

  fn val_for(&self, key: &Key) -> Value {
    self.externs.val_for(key)
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
  fn product(&self) -> &TypeConstraint {
    &self.selector.product
  }

  /**
   * Returns the `name` field of the given item.
   *
   * TODO: There are at least two hacks here. Because we don't have access to the appropriate
   * `str` type, we just assume that it has the same type as the name of the field. And more
   * importantly, there is no check that the object _has_ a name field.
   */
  fn field_name(tasks: &Tasks, externs: &Externs, item: &Value) -> String {
    let name_val = externs.project(item, &tasks.field_name, tasks.field_name.0.type_id());
    externs.val_to_str(&name_val)
  }

  fn select_literal_single<'a>(
    &self,
    tasks: &Tasks,
    externs: &Externs,
    candidate: &'a Value,
    variant_value: Option<&str>
  ) -> bool {
    if !externs.satisfied_by(&self.selector.product, candidate.type_id()) {
      return false;
    }
    return match variant_value {
      Some(vv) if Select::field_name(tasks, externs, candidate) != *vv =>
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
    tasks: &Tasks,
    externs: &Externs,
    candidate: Value,
    variant_value: Option<&str>
  ) -> Option<Value> {
    // Check whether the subject is-a instance of the product.
    if self.select_literal_single(tasks, externs, &candidate, variant_value) {
      return Some(candidate)
    }

    // Else, check whether it has-a instance of the product.
    // TODO: returning only the first literal configuration of a given type/variant. Need to
    // define mergeability for products.
    if externs.satisfied_by(&tasks.type_has_products, candidate.type_id()) {
      for child in externs.project_multi(&candidate, &tasks.field_products) {
        if self.select_literal_single(tasks, externs, &child, variant_value) {
          return Some(child);
        }
      }
    }
    return None;
  }
}

impl Step for Select {
  fn step(&self, context: StepContext) -> State {
    // TODO add back support for variants https://github.com/pantsbuild/pants/issues/4020
    let variants = &self.variants;

    // If there is a variant_key, see whether it has been configured; if not, no match.
    let variant_value: Option<&str> =
      match self.selector.variant_key {
        Some(ref variant_key) => {
          let variant_value = variants.find(variant_key);
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
    if let Some(literal_value) =
      self.select_literal(
        context.tasks,
        context.externs,
        context.externs.val_for(&self.subject),
        variant_value
      ) {
      return State::Complete(Complete::Return(literal_value));
    }

    // Else, attempt to use a configured task to compute the value.
    let mut dependencies = Vec::new();
    let mut matches: Vec<Value> = Vec::new();
    for dep_node in context.gen_nodes(&self.subject, self.product(), &self.variants) {
      match context.graph.get(&dep_node) {
        Some(&Complete::Return(ref value)) => {
          if let Some(v) =
            self.select_literal(
              context.tasks,
              context.externs,
              context.externs.clone_val(value),
              variant_value
            ) {
            matches.push(v);
          }
        },
        Some(&Complete::Noop(_, _)) =>
          continue,
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(context.externs.clone_val(msg))),
        None =>
          dependencies.push(dep_node),
      }
    }

    // If any dependencies were unavailable, wait for them; otherwise, determine whether
    // a value was successfully selected.
    if !dependencies.is_empty() {
      // A dependency has not run yet.
      return State::Waiting;
    } else if matches.len() > 1 {
      // TODO: Multiple successful tasks are not currently supported. We should allow for this
      // by adding support for "mergeable" products. see:
      //   https://github.com/pantsbuild/pants/issues/2526
      return State::Complete(
        Complete::Throw(
          context.externs.create_exception(
            format!("Conflicting values produced for subject and type.")
          )
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
  fn step(&self, context: StepContext) -> State {
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
  fn dep_product<'g>(&self, graph: &'g mut GraphContext, externs: &Externs) -> Result<&'g Value, State> {
    // Request the product we need in order to request dependencies.
    let dep_product_node =
      Node::create(
        Selector::select(self.selector.dep_product),
        self.subject.clone(),
        self.variants.clone()
      );
    match graph.get(&dep_product_node) {
      Some(&Complete::Return(ref value)) =>
        Ok(value),
      Some(&Complete::Noop(_, _)) =>
        Err(
          State::Complete(
            Complete::Noop("Could not compute {} to determine deps.", Some(dep_product_node))
          )
        ),
      Some(&Complete::Throw(ref msg)) =>
        Err(State::Complete(Complete::Throw(externs.clone_val(msg)))),
      None =>
        Err(State::Waiting),
    }
  }

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

  fn store(&self, externs: &Externs, dep_product: &Value, dep_values: Vec<&Value>) -> Value {
    if self.selector.transitive && externs.satisfied_by(&self.selector.product, dep_product.type_id())  {
      // If the dep_product is an inner node in the traversal, prepend it to the list of
      // items to be merged.
      // TODO: would be nice to do this in one operation.
      let prepend = externs.store_list(vec![dep_product], false);
      let mut prepended = dep_values;
      prepended.insert(0, &prepend);
      externs.store_list(prepended, self.selector.transitive)
    } else {
      // Not an inner node, or not a traversal.
      externs.store_list(dep_values, self.selector.transitive)
    }
  }
}

impl Step for SelectDependencies {
  fn step(&self, context: StepContext) -> State {
    // Select the product holding the dependency list.
    let dep_product =
      match self.dep_product(context.graph, context.externs) {
        Ok(dep_product) => context.externs.clone_val(dep_product),
        Err(state) => return state,
      };

    // The product and its dependency list are available.
    let mut has_dependencies = false;
    let mut dep_values = Vec::new();
    for dep_subject in context.externs.project_multi(&dep_product, &self.selector.field) {
      let dep_node = self.dep_node(&context, &dep_subject);
      match context.graph.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(context.externs.clone_val(value)),
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Throw(
              context.externs.create_exception(
                format!(
                  "No source of explicit dep {}",
                  dep_node.format(&context.externs)
                )
              )
            )
          ),
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(context.externs.clone_val(msg))),
        None =>
          has_dependencies = true,
      }
    }

    if has_dependencies {
      State::Waiting
    } else {
      State::Complete(
        Complete::Return(
          self.store(context.externs, &dep_product, dep_values.iter().collect())
        )
      )
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
        self.subject.clone(),
        self.variants.clone()
      );
    let dep_product =
      match context.graph.get(&input_node) {
        Some(&Complete::Return(ref value)) =>
          context.externs.clone_val(value),
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Noop("Could not compute {} to project its field.", Some(input_node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          return State::Complete(Complete::Throw(context.externs.clone_val(msg))),
        None =>
          return State::Waiting,
      };

    // The input product is available: use it to construct the new Subject.
    let projected_subject =
      context.externs.project(
        &dep_product,
        &self.selector.field,
        &self.selector.projected_subject
      );

    // When the output product is available, return it.
    let output_node =
      Node::create(
        Selector::select(self.selector.product),
        context.key_for(&projected_subject),
        self.variants.clone()
      );
    match context.graph.get(&output_node) {
      Some(&Complete::Return(ref value)) =>
        State::Complete(Complete::Return(context.externs.clone_val(value))),
      Some(&Complete::Noop(_, _)) =>
        State::Complete(
          Complete::Throw(
            context.externs.create_exception(
              format!(
                "No source of projected dependency {}",
                output_node.format(&context.externs)
              )
            )
          )
        ),
      Some(&Complete::Throw(ref msg)) =>
        // NB: propagate thrown exception directly.
        State::Complete(Complete::Throw(context.externs.clone_val(msg))),
      None =>
        State::Waiting,
    }
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
  fn step(&self, context: StepContext) -> State {
    // Compute dependencies for the Node, or determine whether it is a Noop.
    let mut has_dependencies = false;
    let mut dep_values: Vec<Value> = Vec::new();
    for selector in &self.selector.clause {
      let dep_node =
        Node::create(
          selector.clone(),
          self.subject.clone(),
          self.variants.clone()
        );
      match context.graph.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(context.externs.clone_val(value)),
        Some(&Complete::Noop(_, _)) =>
          return State::Complete(
            Complete::Noop("Was missing (at least) input {}.", Some(dep_node))
          ),
        Some(&Complete::Throw(ref msg)) =>
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(context.externs.clone_val(msg))),
        None =>
          has_dependencies = true,
      }
    }

    if has_dependencies {
      // A clause was still waiting on dependencies.
      State::Waiting
    } else {
      // Ready to run!
      let tasks = &context.tasks;
      State::Runnable(Runnable {
        func: self.selector.func,
        args: dep_values,
        cacheable: self.selector.cacheable,
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

  pub fn step<'g>(&self, graph: &'g mut GraphContext<'g>, tasks: &Tasks) -> State {
    let context =
      StepContext {
        graph: graph,
        tasks: tasks,
        externs: &tasks.externs,
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
