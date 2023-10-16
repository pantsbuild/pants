// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
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
// TODO: See https://github.com/PyO3/pyo3/issues/2555
#![allow(clippy::borrow_deref_ref)]
#![type_length_limit = "43757804"]

#[macro_use]
extern crate derivative;

mod context;
mod downloads;
mod externs;
mod interning;
mod intrinsics;
mod nodes;
mod python;
mod scheduler;
mod selectors;
mod session;
mod tasks;
mod types;

pub use crate::context::{
    Context, Core, ExecutionStrategyOptions, LocalStoreOptions, RemotingOptions,
};
pub use crate::intrinsics::Intrinsics;
pub use crate::python::{Failure, Function, Key, Params, TypeId, Value};
pub use crate::scheduler::{ExecutionRequest, ExecutionTermination, Scheduler};
pub use crate::session::Session;
pub use crate::tasks::{Intrinsic, Rule, Tasks};
pub use crate::types::Types;
