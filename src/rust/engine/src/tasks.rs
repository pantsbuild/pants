// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};

use core::{Field, Function, Key, TypeConstraint, TypeId, Value, FNV};
use externs;
use selectors::{Get, Select, SelectDependencies, Selector};
use types::Types;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  pub product: TypeConstraint,
  pub clause: Vec<Selector>,
  pub gets: Vec<Get>,
  pub func: Function,
  pub cacheable: bool,
}

///
/// Registry of native (rust) Intrinsic tasks, user (python) Tasks, and Singletons.
///
#[derive(Clone)]
pub struct Tasks {
  // output product type -> Intrinsic providing it
  intrinsics: HashMap<TypeConstraint, Intrinsic, FNV>,
  // Singleton Values to be returned for a given TypeConstraint.
  singletons: HashMap<TypeConstraint, (Key, Value), FNV>,
  // output product type -> list of tasks providing it
  tasks: HashMap<TypeConstraint, Vec<Task>, FNV>,
  // Used during the construction of the tasks map.
  preparing: Option<Task>,
}

///
/// Defines a stateful lifecycle for defining tasks via the C api. Call in order:
///   1. task_begin() - once per task
///   2. add_*() - zero or more times per task to add input clauses
///   3. task_end() - once per task
///
/// Also has a one-shot method for adding a singleton (which has no Selectors):
///   1. singleton_add()
///
/// (This protocol was original defined in a Builder, but that complicated the C lifecycle.)
///
impl Tasks {
  pub fn new() -> Tasks {
    Tasks {
      intrinsics: Default::default(),
      singletons: Default::default(),
      tasks: Default::default(),
      preparing: None,
    }
  }

  pub fn all_product_types(&self) -> HashSet<TypeConstraint> {
    self
      .singletons
      .keys()
      .chain(self.tasks.keys())
      .cloned()
      .collect::<HashSet<_>>()
  }

  pub fn all_tasks(&self) -> Vec<&Task> {
    self.tasks.values().flat_map(|tasks| tasks).collect()
  }

  pub fn gen_singleton(&self, product: &TypeConstraint) -> Option<&(Key, Value)> {
    self.singletons.get(product)
  }

  pub fn gen_intrinsic(&self, product: &TypeConstraint) -> Option<&Intrinsic> {
    self.intrinsics.get(product)
  }

  pub fn gen_tasks(&self, product: &TypeConstraint) -> Option<&Vec<Task>> {
    self.tasks.get(product)
  }

  pub fn intrinsics_set(&mut self, types: &Types) {
    self.intrinsics = vec![
      Intrinsic {
        kind: IntrinsicKind::Snapshot,
        product: types.snapshot,
        input: types.path_globs,
      },
      Intrinsic {
        kind: IntrinsicKind::FilesContent,
        product: types.files_content,
        input: types.snapshot,
      },
      Intrinsic {
        kind: IntrinsicKind::ProcessExecution,
        product: types.process_result,
        input: types.process_request,
      },
    ].into_iter()
      .map(|i| (i.product.clone(), i))
      .collect();
  }

  pub fn singleton_add(&mut self, value: Value, product: TypeConstraint) {
    if let Some(&(_, ref existing_value)) = self.singletons.get(&product) {
      panic!(
        "More than one singleton rule was installed for the product {:?}: {:?} vs {:?}",
        product, existing_value, value,
      );
    }
    self
      .singletons
      .insert(product, (externs::key_for(value.clone()), value));
  }

  ///
  /// The following methods define the Task registration lifecycle.
  ///
  pub fn task_begin(&mut self, func: Function, product: TypeConstraint) {
    assert!(
      self.preparing.is_none(),
      "Must `end()` the previous task creation before beginning a new one!"
    );

    self.preparing = Some(Task {
      cacheable: true,
      product: product,
      clause: Vec::new(),
      gets: Vec::new(),
      func: func,
    });
  }

  pub fn add_get(&mut self, product: TypeConstraint, subject: TypeId) {
    self
      .preparing
      .as_mut()
      .expect("Must `begin()` a task creation before adding gets!")
      .gets
      .push(Get {
        product: product,
        subject: subject,
      });
  }

  pub fn add_select(&mut self, product: TypeConstraint, variant_key: Option<String>) {
    self.clause(Selector::Select(Select {
      product: product,
      variant_key: variant_key,
    }));
  }

  pub fn add_select_dependencies(
    &mut self,
    product: TypeConstraint,
    dep_product: TypeConstraint,
    field: Field,
    field_types: Vec<TypeId>,
  ) {
    self.clause(Selector::SelectDependencies(SelectDependencies {
      product: product,
      dep_product: dep_product,
      field: field,
      field_types: field_types,
    }));
  }

  fn clause(&mut self, selector: Selector) {
    self
      .preparing
      .as_mut()
      .expect("Must `begin()` a task creation before adding clauses!")
      .clause
      .push(selector);
  }

  pub fn task_end(&mut self) {
    // Move the task from `preparing` to the Tasks map
    let mut task = self
      .preparing
      .take()
      .expect("Must `begin()` a task creation before ending it!");
    let tasks = self
      .tasks
      .entry(task.product.clone())
      .or_insert_with(|| Vec::new());
    assert!(
      !tasks.contains(&task),
      "{:?} was double-registered for {:?}: {:?}",
      task,
      task.product,
      tasks,
    );
    task.clause.shrink_to_fit();
    task.gets.shrink_to_fit();
    tasks.push(task);
  }
}

// TODO: This definition of `Intrinsic` is broken. Like `Tasks`, Intrinsics may have zero or more
// input type requirements. As an example, `Snapshot` should have zero inputs, but currently it
// "depends on" the subgraph that instantiates its PathGlobs object.
#[derive(Eq, Hash, PartialEq, Clone, Copy, Debug)]
pub struct Intrinsic {
  pub kind: IntrinsicKind,
  pub product: TypeConstraint,
  pub input: TypeConstraint,
}

#[derive(Eq, Hash, PartialEq, Clone, Copy, Debug)]
pub enum IntrinsicKind {
  Snapshot,
  FilesContent,
  ProcessExecution,
}
