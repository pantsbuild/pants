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
use parking_lot::Mutex;
use rand::thread_rng;
use rand::Rng;
use tokio::task_local;

use std::cell::RefCell;
use std::future::Future;
use std::sync::Arc;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct WorkUnit {
  pub name: String,
  pub time_span: TimeSpan,
  pub span_id: String,
  pub parent_id: Option<String>,
  pub metadata: WorkunitMetadata,
}

pub struct StartedWorkUnit {
  pub name: String,
  pub start_time: std::time::SystemTime,
  pub span_id: String,
  pub parent_id: Option<String>,
  pub metadata: WorkunitMetadata,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Default)]
pub struct WorkunitMetadata {
  pub desc: Option<String>,
}

impl StartedWorkUnit {
  pub fn finish(self) -> WorkUnit {
    WorkUnit {
      name: self.name,
      time_span: TimeSpan::since(&self.start_time),
      span_id: self.span_id,
      parent_id: self.parent_id,
      metadata: self.metadata,
    }
  }
}

impl WorkUnit {
  pub fn new(name: String, time_span: TimeSpan, parent_id: Option<String>) -> WorkUnit {
    let span_id = generate_random_64bit_string();
    WorkUnit {
      name,
      time_span,
      span_id,
      parent_id,
      metadata: WorkunitMetadata::default(),
    }
  }
}

#[derive(Clone, Default)]
pub struct WorkUnitStore {
  inner: Arc<Mutex<WorkUnitInnerStore>>,
}

#[derive(Default)]
pub struct WorkUnitInnerStore {
  pub workunits: Vec<WorkUnit>,
  last_seen_workunit: usize,
}

impl WorkUnitStore {
  pub fn new() -> WorkUnitStore {
    WorkUnitStore {
      inner: Arc::new(Mutex::new(WorkUnitInnerStore {
        workunits: Vec::new(),
        last_seen_workunit: 0,
      })),
    }
  }

  pub fn get_workunits(&self) -> Arc<Mutex<WorkUnitInnerStore>> {
    self.inner.clone()
  }

  pub fn add_workunit(&self, workunit: WorkUnit) {
    self.inner.lock().workunits.push(workunit);
  }

  pub fn with_latest_workunits<F, T>(&mut self, f: F) -> T
  where
    F: FnOnce(&[WorkUnit]) -> T,
  {
    let mut inner_guard = (*self.inner).lock();
    let inner_store: &mut WorkUnitInnerStore = &mut *inner_guard;
    let workunits = &inner_store.workunits;
    let cur_len = workunits.len();
    let latest: usize = inner_store.last_seen_workunit;

    let output = f(&workunits[latest..cur_len]);
    inner_store.last_seen_workunit = cur_len;
    output
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

thread_local! {
  static THREAD_PARENT_ID: RefCell<Option<String>> = RefCell::new(None)
}

task_local! {
  static TASK_PARENT_ID: Option<String>;
}

///
/// Set the current parent_id for a Thread, but _not_ for a Task. Tasks must always be spawned
/// by callers using the `scope_task_parent_id` helper (generally via task_executor::Executor.)
///
pub fn set_thread_parent_id(parent_id: Option<String>) {
  THREAD_PARENT_ID.with(|thread_parent_id| {
    *thread_parent_id.borrow_mut() = parent_id;
  })
}

///
/// Propagate the current parent_id to a Future representing a newly spawned Task. Usage of
/// this method should mostly be contained to task_executor::Executor.
///
pub async fn scope_task_parent_id<F>(parent_id: Option<String>, f: F) -> F::Output
where
  F: Future,
{
  TASK_PARENT_ID.scope(parent_id, f).await
}

pub fn get_parent_id() -> Option<String> {
  if let Ok(Some(parent_id)) = TASK_PARENT_ID.try_with(|parent_id| parent_id.clone()) {
    Some(parent_id)
  } else {
    THREAD_PARENT_ID.with(|parent_id| parent_id.borrow().clone())
  }
}

#[cfg(test)]
mod tests;
