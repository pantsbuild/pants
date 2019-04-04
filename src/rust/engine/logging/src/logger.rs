// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::TryIntoPythonLogLevel;
use lazy_static::lazy_static;
use log::{log, set_logger, set_max_level, LevelFilter, Log, Metadata, Record};
use parking_lot::Mutex;
use simplelog::Config;
use simplelog::WriteLogger;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::{stderr, Stderr, Write};
use std::path::PathBuf;

lazy_static! {
  pub static ref LOGGER: Logger = Logger::new();
}

pub struct Logger {
  pantsd_log: Mutex<MaybeWriteLogger<File>>,
  // TODO We may want to replace this with logging to an arbitrary file descriptor,
  // but we never need it right now.
  stderr_log: Mutex<MaybeWriteLogger<Stderr>>,
}

impl Logger {
  pub fn new() -> Logger {
    Logger {
      pantsd_log: Mutex::new(MaybeWriteLogger::empty()),
      stderr_log: Mutex::new(MaybeWriteLogger::empty()),
    }
  }

  pub fn init(max_level: u64) {
    let max_python_level = (max_level).try_into_PythonLogLevel();
    match max_python_level {
      Ok(python_level) => {
        let level: log::LevelFilter = python_level.into();
        set_max_level(level);
        set_logger(&*LOGGER).expect("Error setting up global logger.");
      }
      Err(err) => panic!("Unrecognised log level from python: {}: {}", max_level, err),
    };
  }

  fn maybe_increase_global_verbosity(&self, new_level: log::LevelFilter) {
    if log::max_level() < new_level {
      set_max_level(new_level);
    }
  }

  pub fn set_stderr_logger(&self, python_level: u64) -> Result<(), String> {
    python_level.try_into_PythonLogLevel().map(|level| {
      self.maybe_increase_global_verbosity(level.into());
      *self.stderr_log.lock() = MaybeWriteLogger::new(stderr(), level.into())
    })
  }

  ///
  /// Set up a file logger which logs at python_level to log_file_path.
  /// Returns the file descriptor of the log file.
  ///
  #[cfg(unix)]
  pub fn set_pantsd_logger(
    &self,
    log_file_path: PathBuf,
    python_level: u64,
  ) -> Result<std::os::unix::io::RawFd, String> {
    use std::os::unix::io::AsRawFd;
    python_level.try_into_PythonLogLevel().and_then(|level| {
      {
        // Maybe close open file by dropping the existing logger
        *self.pantsd_log.lock() = MaybeWriteLogger::empty();
      }
      OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_file_path)
        .map(|file| {
          let fd = file.as_raw_fd();
          self.maybe_increase_global_verbosity(level.into());
          *self.pantsd_log.lock() = MaybeWriteLogger::new(file, level.into());
          fd
        })
        .map_err(|err| format!("Error opening pantsd logfile: {}", err))
    })
  }

  pub fn log_from_python(
    &self,
    message: &str,
    python_level: u64,
    target: &str,
  ) -> Result<(), String> {
    python_level.try_into_PythonLogLevel().map(|level| {
      log!(target: target, level.into(), "{}", message);
    })
  }
}

impl Log for Logger {
  fn enabled(&self, _metadata: &Metadata) -> bool {
    // Individual log levels are handled by each sub-logger,
    // And a global filter is applied to set_max_level.
    // No need to filter here.
    true
  }

  fn log(&self, record: &Record) {
    self.stderr_log.lock().log(record);
    self.pantsd_log.lock().log(record);
  }

  fn flush(&self) {
    self.stderr_log.lock().flush();
    self.pantsd_log.lock().flush();
  }
}

struct MaybeWriteLogger<W: Write + Send + 'static> {
  level: LevelFilter,
  inner: Option<Box<WriteLogger<W>>>,
}

impl<W: Write + Send + 'static> MaybeWriteLogger<W> {
  pub fn empty() -> MaybeWriteLogger<W> {
    MaybeWriteLogger {
      level: LevelFilter::Off,
      inner: None,
    }
  }

  pub fn new(writable: W, level: LevelFilter) -> MaybeWriteLogger<W> {
    // We initialize the inner WriteLogger with no filters so that we don't
    // have to create a new one every time we change the level of the outer
    // MaybeWriteLogger.
    MaybeWriteLogger {
      level,
      inner: Some(WriteLogger::new(
        LevelFilter::max(),
        Config::default(),
        writable,
      )),
    }
  }

  pub fn level(&self) -> LevelFilter {
    self.level
  }
}

impl<W: Write + Send + 'static> Log for MaybeWriteLogger<W> {
  fn enabled(&self, metadata: &Metadata) -> bool {
    metadata.level() <= self.level()
  }

  fn log(&self, record: &Record) {
    if !self.enabled(record.metadata()) {
      return;
    }
    if let Some(ref logger) = self.inner {
      logger.log(record);
    }
  }

  fn flush(&self) {
    if let Some(ref logger) = self.inner {
      logger.flush();
    }
  }
}
