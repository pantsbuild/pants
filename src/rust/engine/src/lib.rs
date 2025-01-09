// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

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
mod session;
mod tasks;
mod types;

pub use crate::context::{
    Context, Core, ExecutionStrategyOptions, LocalStoreOptions, RemotingOptions, SessionCore,
};
pub use crate::python::{Failure, Function, Key, Params, TypeId, Value};
pub use crate::scheduler::{ExecutionRequest, ExecutionTermination, Scheduler};
pub use crate::session::Session;
pub use crate::tasks::{Rule, Tasks};
pub use crate::types::Types;
