use core::{Key, TypeId, Variants};
use selectors::{Selector, Select, SelectDependencies, SelectVariant, SelectLiteral, SelectProjection};
use std::collections::{HashMap, HashSet};

struct Task {
  output_type: TypeId,
  input_clause: Vec<Selector>,
  func: Key,
}

impl Task {
  pub fn func(&self) -> Key {
    self.func
  }

  pub fn input_clause(&self) -> Vec<Selector> {
    self.input_clause
  }
}

/**
 * Tasks able to produce each type.
 */
pub type Tasks = HashMap<TypeId, Vec<Task>>;

/**
 * Defines a stateful lifecycle for defining tasks via the C api. Call in order:
 *   0. new() - once
 *   1. task_gen() - once per task
 *   2. add_*() - zero or more times per task to add input clauses
 *   3. task_end() - once per task
 *   4. build() - once to create the Tasks struct.
 */
pub struct TasksBuilder {
  // Tasks able to produce each type.
  tasks: HashMap<TypeId, Vec<Task>>,
  // Used during the construction of the tasks map via the C api.
  preparing: Option<Task>,
}

pub impl TasksBuilder {
  pub fn new() -> TasksBuilder {
    TasksBuilder {
      tasks: HashMap::new(),
      preparing: None,
    }
  }

  pub fn task_gen(&mut self, func: Key, output_type: TypeId) {
    assert!(
      self.preparing.is_none(),
      "Must `end()` the previous task creation before beginning a new one!"
    );

    self.preparing =
      Some(
        Task {
          output_type: output_type,
          input_clause: Vec::new(),
          func: func,
        }
      );
  }

  pub fn add_select(&mut self, product: TypeId, optional: bool) {
    self.clause(Selector::Select(
      Select { product: product, optional: optional }
    ));
  }

  pub fn add_select_variant(&mut self, product: TypeId, variant_key: String) {
    self.clause(Selector::SelectVariant(
      SelectVariant { product: product, variant_key: variant_key }
    ));
  }

  pub fn add_select_dependencies(&mut self, product: TypeId, dep_product: TypeId, field: String) {
    self.clause(Selector::SelectDependencies(
      SelectDependencies { product: product, dep_product: dep_product, field: field }
    ));
  }

  pub fn add_select_projection(&mut self, product: TypeId, projected_subject: TypeId, fields: Vec<String>, input_product: TypeId) {
    self.clause(Selector::SelectProjection(
      SelectProjection { product: product, projected_subject: projected_subject, fields: fields, input_product: input_product }
    ));
  }

  pub fn add_select_literal(&mut self, subject: Key, product: TypeId) {
    self.clause(Selector::SelectLiteral(
      SelectLiteral { subject: subject, product: product }
    ));
  }

  fn clause(&mut self, selector: Selector) {
    self.preparing
      .expect("Must `begin()` a task creation before adding clauses!")
      .input_clause.push(selector);
  }

  pub fn task_end(&mut self) {
    assert!(
      self.preparing.is_some(),
      "Must `begin()` a task creation before ending it!"
    );

    // Move the task from `preparing` to the Tasks map
    let task = self.preparing.take().expect("Must `begin()` a task creation before ending it!");

    self.tasks.entry(task.output_type).or_insert(Vec::new()).push(task);
  }

  pub fn build(self) -> Tasks {
    self.tasks
  }
}
