use core::{Field, Function, IsInstanceFunction, Key, TypeId};
use selectors::{Selector, Select, SelectDependencies, SelectLiteral, SelectProjection};
use std::collections::HashMap;

pub struct Task {
  output_type: TypeId,
  input_clause: Vec<Selector>,
  func: Function,
}

impl Task {
  pub fn func(&self) -> &Function {
    &self.func
  }

  pub fn input_clause(&self) -> &Vec<Selector> {
    &self.input_clause
  }
}

/**
 * Registry of tasks able to produce each type, along with a few fundamental python
 * types that the engine must be aware of.
 */
pub struct Tasks {
  tasks: HashMap<TypeId, Vec<Task>>,
  isinstance: IsInstanceFunction,
  field_name: Field,
  field_products: Field,
  field_variants: Field,
  type_address: TypeId,
  type_has_products: TypeId,
  type_has_variants: TypeId,
  // Used during the construction of the tasks map.
  preparing: Option<Task>,
}

/**
 * Defines a stateful lifecycle for defining tasks via the C api. Call in order:
 *   1. task_gen() - once per task
 *   2. add_*() - zero or more times per task to add input clauses
 *   3. task_end() - once per task
 *
 * (This protocol was original defined in a Builder, but that complicated the C lifecycle.)
 */
impl Tasks {
  pub fn new(
    isinstance: IsInstanceFunction,
    field_name: Field,
    field_products: Field,
    field_variants: Field,
    type_address: TypeId,
    type_has_products: TypeId,
    type_has_variants: TypeId,
  ) -> Tasks {
    Tasks {
      tasks: HashMap::new(),
      isinstance: isinstance,
      field_name: field_name,
      field_products: field_products,
      field_variants: field_variants,
      type_address: type_address,
      type_has_products: type_has_products,
      type_has_variants: type_has_variants,
      preparing: None,
    }
  }

  pub fn get(&self, type_id: &TypeId) -> Option<&Vec<Task>> {
    self.tasks.get(type_id)
  }

  pub fn field_name(&self) -> &Field {
    &self.field_name
  }

  pub fn field_products(&self) -> &Field {
    &self.field_products
  }

  pub fn field_variants(&self) -> &Field {
    &self.field_variants
  }

  pub fn type_address(&self) -> &TypeId {
    &self.type_address
  }

  pub fn type_has_products(&self) -> &TypeId {
    &self.type_has_products
  }

  pub fn type_has_variants(&self) -> &TypeId {
    &self.type_has_variants
  }

  /**
   * The following methods define the Task registration lifecycle.
   */

  pub fn task_gen(&mut self, func: Function, output_type: TypeId) {
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

  pub fn add_select(&mut self, product: TypeId, variant_key: Option<Key>) {
    self.clause(Selector::Select(
      Select { product: product, variant_key: variant_key }
    ));
  }

  pub fn add_select_dependencies(&mut self, product: TypeId, dep_product: TypeId, field: Field) {
    self.clause(Selector::SelectDependencies(
      SelectDependencies { product: product, dep_product: dep_product, field: field }
    ));
  }

  pub fn add_select_projection(&mut self, product: TypeId, projected_subject: TypeId, field: Field, input_product: TypeId) {
    self.clause(Selector::SelectProjection(
      SelectProjection { product: product, projected_subject: projected_subject, field: field, input_product: input_product }
    ));
  }

  pub fn add_select_literal(&mut self, subject: Key, product: TypeId) {
    self.clause(Selector::SelectLiteral(
      SelectLiteral { subject: subject, product: product }
    ));
  }

  fn clause(&mut self, selector: Selector) {
    self.preparing.as_mut()
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

    self.tasks.entry(task.output_type.clone()).or_insert(Vec::new()).push(task);
  }
}
