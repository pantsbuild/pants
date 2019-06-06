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

use parking_lot::Mutex;

pub struct WorkUnit {
  pub name: String,
  pub start_timestamp: f64,
  pub end_timestamp: f64,
  pub span_id: String,
}

pub trait WorkUnitStore {
  fn should_record_zipkin_spans(&self) -> bool;
  fn get_workunits(&self) -> &Mutex<Vec<WorkUnit>>;
  fn add_workunit(&self, workunit: WorkUnit);
}
