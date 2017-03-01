// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;

use core::{Field, Function, FNV, Key, TypeConstraint, TypeId};
use selectors::{Selector, Select, SelectDependencies, SelectLiteral, SelectProjection};


#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  pub product: TypeConstraint,
  pub clause: Vec<Selector>,
  pub func: Function,
  pub cacheable: bool,
}

/**
 * Registry of tasks able to produce each type, along with a few fundamental python
 * types that the engine must be aware of.
 */
pub struct Tasks {
  // subject_type, selector -> list of tasks implementing it
  intrinsics: HashMap<(TypeId, TypeConstraint), Vec<Task>, FNV>,
  // any-subject, selector -> list of tasks implementing it
  singletons: HashMap<TypeConstraint, Vec<Task>, FNV>,
  // any-subject, selector -> list of tasks implementing it
  tasks: HashMap<TypeConstraint, Vec<Task>, FNV>,
  pub field_name: Field,
  pub field_products: Field,
  pub field_variants: Field,
  pub type_address: TypeConstraint,
  pub type_has_products: TypeConstraint,
  pub type_has_variants: TypeConstraint,
  // Used during the construction of the tasks map.
  preparing: Option<Task>,
}

/**
 * Defines a stateful lifecycle for defining tasks via the C api. Call in order:
 *   1. task_add() - once per task
 *   2. add_*() - zero or more times per task to add input clauses
 *   3. task_end() - once per task
 *
 * Also has a one-shot method for adding an intrinsic Task (which have no Selectors):
 *   1. intrinsic_add()
 *
 * (This protocol was original defined in a Builder, but that complicated the C lifecycle.)
 */
impl Tasks {
  pub fn new(
    field_name: Field,
    field_products: Field,
    field_variants: Field,
    type_address: TypeConstraint,
    type_has_products: TypeConstraint,
    type_has_variants: TypeConstraint,
  ) -> Tasks {
    Tasks {
      intrinsics: Default::default(),
      singletons: Default::default(),
      tasks: Default::default(),
      field_name: field_name,
      field_products: field_products,
      field_variants: field_variants,
      type_address: type_address,
      type_has_products: type_has_products,
      type_has_variants: type_has_variants,
      preparing: None,
    }
  }

  pub fn all_product_types(&self) -> Vec<TypeConstraint> {
    let mut product_types: Vec<_> = self.all_rules().iter().map(|t| t.product).collect();
    // NB sorted by id so that dedup will consolidate runs of duplicates.
    product_types.sort_by_key(|tc| tc.0);
    product_types.dedup();
    product_types
  }

  pub fn is_singleton_task(&self, sought_task: &Task) -> bool {
    self.singletons.values().any(|tasks| tasks.iter().any(|t| t == sought_task))
  }

  pub fn is_intrinsic_task(&self, sought_task: &Task) -> bool {
    self.intrinsics.values().any(|tasks| tasks.iter().any(|t| t == sought_task))
  }

  pub fn all_rules(&self) -> Vec<&Task> {
    self.singletons.values()
      .chain(self.intrinsics.values())
      .chain(self.tasks.values())
      .flat_map(|tasks| tasks)
      .collect()
  }

  pub fn gen_tasks(&self, subject_type: &TypeId, product: &TypeConstraint) -> Option<&Vec<Task>> {
    // Use singletons, then intrinsics, otherwise tasks.
    self.singletons.get(product)
      .or(self.intrinsics.get(&(*subject_type, *product)))
      .or(self.tasks.get(product))
  }

  pub fn intrinsic_add(
    &mut self,
    func: Function,
    // TODO: The subject_type and subject_constraint are redundant here, but we don't currently
    // have a way to lift a TypeId into a TypeConstraint for that type.
    subject_type: TypeId,
    subject_constraint: TypeConstraint,
    product: TypeConstraint
  ) {
    self.intrinsics.entry((subject_type, product))
      .or_insert_with(||
        vec![
          Task {
            cacheable: false,
            product: product,
            clause: vec![Selector::select(subject_constraint)],
            func: func,
          }
        ]
      );
  }

  pub fn singleton_add(&mut self, func: Function, product: TypeConstraint) {
    self.singletons.entry(product)
      .or_insert_with(||
        vec![
          Task {
            cacheable: false,
            product: product,
            clause: Vec::new(),
            func: func,
          }
        ]
      );
  }

  /**
   * The following methods define the Task registration lifecycle.
   */
  pub fn task_add(&mut self, func: Function, product: TypeConstraint) {
    assert!(
      self.preparing.is_none(),
      "Must `end()` the previous task creation before beginning a new one!"
    );

    self.preparing =
      Some(
        Task {
          cacheable: true,
          product: product,
          clause: Vec::new(),
          func: func,
        }
      );
  }

  pub fn add_select(&mut self, product: TypeConstraint, variant_key: Option<String>) {
    self.clause(Selector::Select(
      Select { product: product, variant_key: variant_key }
    ));
  }

  pub fn add_select_dependencies(&mut self, product: TypeConstraint, dep_product: TypeConstraint, field: Field, field_types: Vec<TypeId>, transitive: bool) {
    self.clause(Selector::SelectDependencies(
      SelectDependencies { product: product, dep_product: dep_product, field: field, field_types: field_types, transitive: transitive }
    ));
  }

  pub fn add_select_projection(&mut self, product: TypeConstraint, projected_subject: TypeId, field: Field, input_product: TypeConstraint) {
    self.clause(Selector::SelectProjection(
      SelectProjection { product: product, projected_subject: projected_subject, field: field, input_product: input_product }
    ));
  }

  pub fn add_select_literal(&mut self, subject: Key, product: TypeConstraint) {
    self.clause(Selector::SelectLiteral(
      SelectLiteral { subject: subject, product: product }
    ));
  }

  fn clause(&mut self, selector: Selector) {
    self.preparing.as_mut()
      .expect("Must `begin()` a task creation before adding clauses!")
      .clause.push(selector);
  }

  pub fn task_end(&mut self) {
    // Move the task from `preparing` to the Tasks map
    let mut task = self.preparing.take().expect("Must `begin()` a task creation before ending it!");
    let mut tasks = self.tasks.entry(task.product.clone()).or_insert_with(|| Vec::new());
    assert!(
      !tasks.contains(&task),
      "{:?} was double-registered for {:?}",
      task,
      task.product,
    );
    task.clause.shrink_to_fit();
    tasks.push(task);
  }
}
