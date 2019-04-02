// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
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
pub mod logger;

pub type Logger = logger::Logger;

use num_enum::CustomTryInto;

// This is a hard-coding of constants in the standard logging python package.
// TODO: Switch from CustomTryInto to TryFromPrimitive when try_from is stable.
#[derive(Debug, Eq, PartialEq, CustomTryInto, Clone, Copy)]
#[repr(u64)]
enum PythonLogLevel {
  NotSet = 0,
  // Trace doesn't exist in a Python world, so set it to "a bit lower than Debug".
  Trace = 5,
  Debug = 10,
  Info = 20,
  Warn = 30,
  Error = 40,
  Critical = 50,
}

impl From<log::Level> for PythonLogLevel {
  fn from(level: log::Level) -> Self {
    match level {
      log::Level::Error => PythonLogLevel::Error,
      log::Level::Warn => PythonLogLevel::Warn,
      log::Level::Info => PythonLogLevel::Info,
      log::Level::Debug => PythonLogLevel::Debug,
      log::Level::Trace => PythonLogLevel::Trace,
    }
  }
}

impl From<PythonLogLevel> for log::LevelFilter {
  fn from(level: PythonLogLevel) -> Self {
    match level {
      PythonLogLevel::NotSet => log::LevelFilter::Off,
      PythonLogLevel::Trace => log::LevelFilter::Trace,
      PythonLogLevel::Debug => log::LevelFilter::Debug,
      PythonLogLevel::Info => log::LevelFilter::Info,
      PythonLogLevel::Warn => log::LevelFilter::Warn,
      PythonLogLevel::Error => log::LevelFilter::Error,
      // Rust doesn't have a Critical, so treat them like Errors.
      PythonLogLevel::Critical => log::LevelFilter::Error,
    }
  }
}

impl From<PythonLogLevel> for log::Level {
  fn from(level: PythonLogLevel) -> Self {
    match level {
      PythonLogLevel::NotSet => {
        panic!("PythonLogLevel::NotSet doesn't have a translation to Level")
      }
      PythonLogLevel::Trace => log::Level::Trace,
      PythonLogLevel::Debug => log::Level::Debug,
      PythonLogLevel::Info => log::Level::Info,
      PythonLogLevel::Warn => log::Level::Warn,
      PythonLogLevel::Error => log::Level::Error,
      // Rust doesn't have a Critical, so treat them like Errors.
      PythonLogLevel::Critical => log::Level::Error,
    }
  }
}
