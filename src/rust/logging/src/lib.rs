// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

///
/// Macro to allow fatal logging to a file which bypasses the standard logging systems.
/// This is useful for code paths which must not interact with stdio or the logging system, and
/// can also be useful for one-off debugging of stdio, logging, or pantsd issues.
///
#[macro_export]
macro_rules! fatal_log {
    ($($arg:tt)+) => {
      {
        use ::std::io::Write;
        let mut f = ::std::fs::OpenOptions::new().create(true).append(true).open("fatal.log").unwrap();
        writeln!(f, $($arg)+).unwrap()
      }
    };
}

pub mod logger;

pub type Logger = logger::PantsLogger;

use num_enum::TryFromPrimitive;

// This is a hard-coding of constants in the standard logging python package.
#[derive(Debug, Eq, PartialEq, TryFromPrimitive, Clone, Copy)]
#[repr(u64)]
pub enum PythonLogLevel {
    NotSet = 0,
    // Trace doesn't exist in a Python world, so set it to "a bit lower than Debug".
    Trace = 5,
    Debug = 10,
    Info = 20,
    Warn = 30,
    Error_ = 40,
    Critical = 50,
}

impl From<log::Level> for PythonLogLevel {
    fn from(level: log::Level) -> Self {
        match level {
            log::Level::Error => PythonLogLevel::Error_,
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
            PythonLogLevel::Error_ => log::LevelFilter::Error,
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
            PythonLogLevel::Error_ => log::Level::Error,
            // Rust doesn't have a Critical, so treat them like Errors.
            PythonLogLevel::Critical => log::Level::Error,
        }
    }
}

mod pants_packages {
    include!(concat!(env!("OUT_DIR"), "/packages.rs"));
}
