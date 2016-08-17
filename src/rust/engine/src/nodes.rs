use std::collections::HashMap;
use std::rc::Rc;

use core::{Key, TypeId, Variants};
use selectors;
use selectors::Selector;
use tasks::Tasks;

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct Runnable {
  func: Key,
  args: Vec<Key>,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub enum State {
  Waiting(Vec<Node>),
  Complete(Complete),
  Runnable(Runnable),
}

/**
 * NB: Throw uses reference-counted strings because we expect there to be a
 * a high degree of duplication when failures are propagated.
 */
#[derive(Debug, Eq, Hash, PartialEq)]
pub enum Complete {
  Noop(String),
  Return(Key),
  Throw(Rc<String>),
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
   *
   * TODO: intrinsics
   */
  fn gen_nodes(&self, subject: &Key, product: TypeId, variants: &Variants) -> Vec<Node> {
    self.tasks.get(&product).map(|tasks|
      tasks.iter()
        .map(|task| {
          Node::Task(
            Task {
              subject: subject.clone(),
              product: product,
              variants: variants.clone(),
              // TODO: cloning out of the task struct is easier than tracking references from
              // Nodes to Tasks... but should likely do it if memory usage becomes an issue.
              func: task.func().clone(),
              clause: task.input_clause().clone(),
            }
          )
        })
        .collect()
    ).unwrap_or_else(|| Vec::new())
  }

  fn get(&self, node: &Node) -> Option<&Complete> {
    self.deps.get(node).map(|c| *c)
  }

  fn none_key(&self) -> &Key {
    self.tasks.none_key()
  }
}

/**
 * Defines executing a single step for the given context.
 */
trait Step {
  fn step(&self, context: StepContext) -> State;
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  subject: Key,
  variants: Variants,
  selector: selectors::Select,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectLiteral {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectLiteral,
}

impl Step for SelectLiteral {
  fn step(&self, _: StepContext) -> State {
    State::Complete(Complete::Return(self.subject.clone()))
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectVariant {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectVariant,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectDependencies {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectDependencies,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  subject: Key,
  product: TypeId,
  variants: Variants,
  func: Key,
  clause: Vec<selectors::Selector>,
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
          self.subject.clone(),
          self.variants.clone()
        );
      match context.get(&dep_node) {
        Some(&Complete::Return(ref value)) =>
          dep_values.push(&value),
        Some(&Complete::Noop(_)) =>
          if selector.optional() {
            dep_values.push(context.none_key());
          } else {
            return State::Complete(
              Complete::Noop(format!("Was missing (at least) input for {:?}.", selector))
            );
          },
        Some(&Complete::Throw(ref msg)) => {
          // NB: propagate thrown exception directly.
          return State::Complete(Complete::Throw(msg.clone()));
        }
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
        func: self.func.clone(),
        args: dep_values.into_iter().map(|d| d.clone()).collect(),
      })
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Filesystem {
  subject: Key,
  product: TypeId,
  variants: Variants,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Node {
  Select(Select),
  SelectLiteral(SelectLiteral),
  SelectVariant(SelectVariant),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  Task(Task),
  Filesystem(Filesystem),
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
      Selector::SelectVariant(s) =>
        Node::SelectVariant(SelectVariant {
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

  pub fn step(&self, deps: HashMap<&Node, &Complete>, tasks: &Tasks) -> State {
    let context =
      StepContext {
        deps: deps,
        tasks: tasks,
      };
    match self {
      &Node::SelectLiteral(ref n) => n.step(context),
      &Node::Task(ref n) => n.step(context),
      n => panic!("TODO! Need to implement step for: {:?}", n),
    }
  }
}
