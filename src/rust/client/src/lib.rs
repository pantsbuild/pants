// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

mod client;
#[cfg(test)]
mod client_tests;

pub use crate::client::execute_command;

#[cfg(test)]
mod lib_tests;
