// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#[cfg(test)]
mod tests;

mod client;
mod server;

pub use client::{client_execute, NailgunClientError};
pub use nails::execution::ExitCode;
pub use server::{RawFdExecution, Server};
