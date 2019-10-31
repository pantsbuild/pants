// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use concrete_time::TimeSpan;
use futures::task_local;
use parking_lot::Mutex;
use rand::thread_rng;
use rand::Rng;
use std::collections::HashSet;
use std::sync::Arc;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct WorkUnit {
  pub name: String,
  pub time_span: TimeSpan,
  pub span_id: String,
  pub parent_id: Option<String>,
}

#[derive(Clone, Default)]
pub struct WorkUnitStore {
  workunits: Arc<Mutex<Vec<WorkUnit>>>,
  last_seen_workunit: usize,
}

impl WorkUnitStore {
  pub fn new() -> WorkUnitStore {
    WorkUnitStore {
      workunits: Arc::new(Mutex::new(Vec::new())),
      last_seen_workunit: 0,
    }
  }

  pub fn get_workunits(&self) -> Arc<Mutex<Vec<WorkUnit>>> {
    self.workunits.clone()
  }

  pub fn add_workunit(&self, workunit: WorkUnit) {
    self.workunits.lock().push(workunit.clone());
  }

  pub fn with_latest_workunits<F, T>(&mut self, f: F) -> T
  where
    F: FnOnce(&[WorkUnit]) -> T,
  {
    let workunits = self.workunits.lock();
    let cur_len = workunits.len();
    let latest = self.last_seen_workunit;
    self.last_seen_workunit = cur_len;
    f(&workunits[latest..cur_len])
  }
}

pub fn generate_random_64bit_string() -> String {
  let mut rng = thread_rng();
  let random_u64: u64 = rng.gen();
  hex_16_digit_string(random_u64)
}

fn hex_16_digit_string(number: u64) -> String {
  format!("{:016.x}", number)
}

pub fn workunits_with_constant_span_id(workunit_store: &WorkUnitStore) -> HashSet<WorkUnit> {
  //  This function is for the test purpose.

  workunit_store
    .get_workunits()
    .lock()
    .iter()
    .map(|workunit| WorkUnit {
      span_id: String::from("ignore"),
      ..workunit.clone()
    })
    .collect()
}

task_local! {
  static TASK_PARENT_ID: Mutex<Option<String>> = Mutex::new(None)
}

pub fn set_parent_id(parent_id: String) {
  TASK_PARENT_ID.with(|task_parent_id| {
    *task_parent_id.lock() = Some(parent_id);
  })
}

pub fn get_parent_id() -> Option<String> {
  TASK_PARENT_ID.with(|task_parent_id| {
    let task_parent_id = task_parent_id.lock();
    (*task_parent_id).clone()
  })
}

#[cfg(test)]
mod tests;
