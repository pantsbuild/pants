// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};

use crate::core::{Function, TypeId, FNV};
use crate::selectors::{Get, Select};
use crate::types::Types;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  pub product: TypeId,
  pub clause: Vec<Select>,
  pub gets: Vec<Get>,
  pub func: Function,
  pub cacheable: bool,
}

///
/// Registry of native (rust) Intrinsic tasks and user (python) Tasks.
///
#[derive(Clone, Debug)]
pub struct Tasks {
  // output product type -> Intrinsic providing it
  intrinsics: HashMap<TypeId, Vec<Intrinsic>, FNV>,
  // output product type -> list of tasks providing it
  tasks: HashMap<TypeId, Vec<Task>, FNV>,
  // Used during the construction of the tasks map.
  preparing: Option<Task>,
}

///
/// Defines a stateful lifecycle for defining tasks via the C api. Call in order:
///   1. task_begin() - once per task
///   2. add_*() - zero or more times per task to add input clauses
///   3. task_end() - once per task
///
/// (This protocol was original defined in a Builder, but that complicated the C lifecycle.)
///
impl Tasks {
  pub fn new() -> Tasks {
    Tasks {
      intrinsics: HashMap::default(),
      tasks: HashMap::default(),
      preparing: None,
    }
  }

  pub fn all_product_types(&self) -> HashSet<TypeId> {
    self
      .tasks
      .keys()
      .chain(self.intrinsics.keys())
      .cloned()
      .collect::<HashSet<_>>()
  }

  pub fn all_tasks(&self) -> Vec<&Task> {
    self.tasks.values().flat_map(|tasks| tasks).collect()
  }

  pub fn gen_intrinsic(&self, product: TypeId) -> Option<&Vec<Intrinsic>> {
    self.intrinsics.get(&product)
  }

  pub fn gen_tasks(&self, product: TypeId) -> Option<&Vec<Task>> {
    self.tasks.get(&product)
  }

  pub fn intrinsics_set(&mut self, types: &Types) {
    let intrinsics = vec![
      Intrinsic {
        product: types.snapshot,
        input: types.path_globs,
      },
      Intrinsic {
        product: types.snapshot,
        input: types.url_to_fetch,
      },
      Intrinsic {
        product: types.snapshot,
        input: types.directory_digest,
      },
      Intrinsic {
        product: types.files_content,
        input: types.directory_digest,
      },
      Intrinsic {
        product: types.directory_digest,
        input: types.directories_to_merge,
      },
      Intrinsic {
        product: types.directory_digest,
        input: types.directory_with_prefix_to_strip,
      },
      Intrinsic {
        product: types.process_result,
        input: types.process_request,
      },
    ];

    self.intrinsics = vec![].into_iter().collect();
    for intrinsic in intrinsics {
      self
        .intrinsics
        .entry(intrinsic.product)
        .or_insert_with(Vec::new)
        .push(intrinsic)
    }
  }

  ///
  /// The following methods define the Task registration lifecycle.
  ///
  pub fn task_begin(&mut self, func: Function, product: TypeId, cacheable: bool) {
    assert!(
      self.preparing.is_none(),
      "Must `end()` the previous task creation before beginning a new one!"
    );

    self.preparing = Some(Task {
      cacheable: cacheable,
      product: product,
      clause: Vec::new(),
      gets: Vec::new(),
      func: func,
    });
  }

  pub fn add_get(&mut self, product: TypeId, subject: TypeId) {
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

  pub fn add_select(&mut self, product: TypeId) {
    self
      .preparing
      .as_mut()
      .expect("Must `begin()` a task creation before adding clauses!")
      .clause
      .push(Select::new(product));
  }

  pub fn task_end(&mut self) {
    // Move the task from `preparing` to the Tasks map
    let mut task = self
      .preparing
      .take()
      .expect("Must `begin()` a task creation before ending it!");
    let tasks = self.tasks.entry(task.product).or_insert_with(Vec::new);
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

#[derive(Eq, Hash, PartialEq, Clone, Copy, Debug)]
pub struct Intrinsic {
  pub product: TypeId,
  pub input: TypeId,
}
