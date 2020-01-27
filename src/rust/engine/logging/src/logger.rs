// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::PythonLogLevel;
use chrono;
use futures01::task_local;
use lazy_static::lazy_static;
use log::{log, set_logger, set_max_level, LevelFilter, Log, Metadata, Record};
use parking_lot::Mutex;
use simplelog::{ConfigBuilder, LevelPadding, WriteLogger};
use std::collections::HashMap;
use std::convert::TryInto;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::{stderr, Stderr, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use ui::EngineDisplay;
use uuid::Uuid;

const TIME_FORMAT_STR: &str = "%H:%M:%S";

lazy_static! {
  pub static ref LOGGER: Logger = Logger::new();
}

pub struct Logger {
  pantsd_log: Mutex<MaybeWriteLogger<File>>,
  stderr_log: Mutex<MaybeWriteLogger<Stderr>>,
  show_rust_3rdparty_logs: AtomicBool,
  engine_display_handles: Mutex<HashMap<Uuid, Arc<Mutex<EngineDisplay>>>>,
}

impl Logger {
  pub fn new() -> Logger {
    Logger {
      pantsd_log: Mutex::new(MaybeWriteLogger::empty()),
      stderr_log: Mutex::new(MaybeWriteLogger::empty()),
      show_rust_3rdparty_logs: AtomicBool::new(true),
      engine_display_handles: Mutex::new(HashMap::new()),
    }
  }

  pub fn init(max_level: u64, show_rust_3rdparty_logs: bool) {
    let max_python_level: Result<PythonLogLevel, _> = max_level.try_into();
    match max_python_level {
      Ok(python_level) => {
        let level: log::LevelFilter = python_level.into();
        set_max_level(level);
        LOGGER
          .show_rust_3rdparty_logs
          .store(show_rust_3rdparty_logs, Ordering::SeqCst);
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
    python_level.try_into().map(|level: PythonLogLevel| {
      self.maybe_increase_global_verbosity(level.into());
      *self.stderr_log.lock() = MaybeWriteLogger::new(
        stderr(),
        level.into(),
        self.show_rust_3rdparty_logs.load(Ordering::SeqCst),
      )
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
    python_level.try_into().and_then(|level: PythonLogLevel| {
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
          *self.pantsd_log.lock() = MaybeWriteLogger::new(
            file,
            level.into(),
            self.show_rust_3rdparty_logs.load(Ordering::SeqCst),
          );
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
    python_level.try_into().map(|level: PythonLogLevel| {
      log!(target: target, level.into(), "{}", message);
    })
  }

  pub fn register_engine_display(&self, engine_display: Arc<Mutex<EngineDisplay>>) -> Uuid {
    let mut handle = self.engine_display_handles.lock();
    let unique_id = Uuid::new_v4();
    handle.insert(unique_id, engine_display);
    unique_id
  }

  pub fn deregister_engine_display(&self, unique_id: Uuid) {
    let mut handle = self.engine_display_handles.lock();
    handle.remove(&unique_id);
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
    let destination = get_destination();
    match destination {
      Destination::Stderr => {
        let mut handles_map = self.engine_display_handles.lock();
        for handle in handles_map.values_mut() {
          let cur_time = chrono::Utc::now().format(TIME_FORMAT_STR);
          let level = record.level();
          let log_string: String = format!("{} [{}] {}", cur_time, level, record.args());
          let mut display_engine = handle.lock();
          display_engine.log(log_string);
        }
        self.stderr_log.lock().log(record)
      }
      Destination::Pantsd => self.pantsd_log.lock().log(record),
    }
  }

  fn flush(&self) {
    self.stderr_log.lock().flush();
    self.pantsd_log.lock().flush();
  }
}

struct MaybeWriteLogger<W: Write + Send + 'static> {
  level: LevelFilter,
  show_rust_3rdparty_logs: bool,
  inner: Option<Box<WriteLogger<W>>>,
}

impl<W: Write + Send + 'static> MaybeWriteLogger<W> {
  pub fn empty() -> MaybeWriteLogger<W> {
    MaybeWriteLogger {
      level: LevelFilter::Off,
      show_rust_3rdparty_logs: true,
      inner: None,
    }
  }

  pub fn new(
    writable: W,
    level: LevelFilter,
    show_rust_3rdparty_logs: bool,
  ) -> MaybeWriteLogger<W> {
    // We initialize the inner WriteLogger with no filters so that we don't
    // have to create a new one every time we change the level of the outer
    // MaybeWriteLogger.

    let config = ConfigBuilder::new()
      .set_time_format_str(TIME_FORMAT_STR)
      .set_thread_level(LevelFilter::Off)
      .set_level_padding(LevelPadding::Off)
      .build();

    MaybeWriteLogger {
      level,
      show_rust_3rdparty_logs,
      inner: Some(WriteLogger::new(LevelFilter::max(), config, writable)),
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
    let mut should_log = self.show_rust_3rdparty_logs;
    if !self.show_rust_3rdparty_logs {
      if let Some(ref module_path) = record.module_path() {
        for pants_package in super::pants_packages::PANTS_PACKAGE_NAMES {
          if &module_path.split("::").next().unwrap() == pants_package {
            should_log = true;
            break;
          }
        }
      } else {
        should_log = true;
      }
    }
    if !should_log {
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

///
/// Thread- or task-local context for where the Logger should send log statements.
///
/// We do this in a per-thread way because we find that Pants threads generally are either
/// daemon-specific or user-facing. We make sure that every time we spawn a thread on the Python
/// side, we set the thread-local information, and every time we submit a Future to a tokio Runtime
/// on the rust side, we set the task-local information.
///
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
#[repr(C)]
pub enum Destination {
  Pantsd,
  Stderr,
}

thread_local! {
  pub static THREAD_DESTINATION: Mutex<Destination> = Mutex::new(Destination::Stderr)
}

task_local! {
  static TASK_DESTINATION: Mutex<Option<Destination>> = Mutex::new(None)
}

pub fn set_destination(destination: Destination) {
  if futures01::task::is_in_task() {
    TASK_DESTINATION.with(|task_destination| {
      *task_destination.lock() = Some(destination);
    })
  } else {
    THREAD_DESTINATION.with(|thread_destination| {
      *thread_destination.lock() = destination;
    })
  }
}

pub fn get_destination() -> Destination {
  fn get_task_destination() -> Option<Destination> {
    TASK_DESTINATION.with(|destination| *destination.lock())
  }

  fn get_thread_destination() -> Destination {
    THREAD_DESTINATION.with(|destination| *destination.lock())
  }

  if futures01::task::is_in_task() {
    get_task_destination().unwrap_or_else(get_thread_destination)
  } else {
    get_thread_destination()
  }
}
