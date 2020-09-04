// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::PythonLogLevel;

use colored::*;
use std::cell::RefCell;
use std::collections::HashMap;
use std::convert::{TryFrom, TryInto};
use std::fs::File;
use std::fs::OpenOptions;
use std::future::Future;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};

use lazy_static::lazy_static;
use log::{debug, log, set_logger, set_max_level, LevelFilter, Log, Metadata, Record};
use parking_lot::Mutex;
use tokio::task_local;
use uuid::Uuid;

const TIME_FORMAT_STR: &str = "%H:%M:%S";

pub type StdioHandler = Box<dyn Fn(&str) -> Result<(), ()> + Send>;

lazy_static! {
  pub static ref PANTS_LOGGER: PantsLogger = PantsLogger::new();
}

pub struct PantsLogger {
  log_file: Mutex<Option<File>>,
  global_level: Mutex<RefCell<LevelFilter>>,
  use_color: AtomicBool,
  show_rust_3rdparty_logs: AtomicBool,
  stderr_handlers: Mutex<HashMap<Uuid, StdioHandler>>,
  show_target: AtomicBool,
  log_level_filters: Mutex<HashMap<String, log::LevelFilter>>,
}

impl PantsLogger {
  pub fn new() -> PantsLogger {
    PantsLogger {
      log_file: Mutex::new(None),
      global_level: Mutex::new(RefCell::new(LevelFilter::Off)),
      show_rust_3rdparty_logs: AtomicBool::new(true),
      use_color: AtomicBool::new(false),
      stderr_handlers: Mutex::new(HashMap::new()),
      show_target: AtomicBool::new(false),
      log_level_filters: Mutex::new(HashMap::new()),
    }
  }

  pub fn init(
    max_level: u64,
    show_rust_3rdparty_logs: bool,
    use_color: bool,
    show_target: bool,
    log_levels_by_target: HashMap<String, u64>,
  ) {
    let log_levels_by_target = log_levels_by_target
      .iter()
      .map(|(k, v)| {
        let python_level: PythonLogLevel = (*v).try_into().unwrap_or_else(|e| {
          panic!("Unrecognized log level from python: {}: {}", v, e);
        });
        let level: log::LevelFilter = python_level.into();
        (k.clone(), level)
      })
      .collect::<HashMap<_, _>>();

    let max_python_level: Result<PythonLogLevel, _> = max_level.try_into();
    match max_python_level {
      Ok(python_level) => {
        let level: LevelFilter = python_level.into();
        // TODO this should be whatever the most verbose log level specified in log_domain_levels -
        // but I'm not sure if it's actually much of a gain over just setting this to Trace.
        set_max_level(LevelFilter::Trace);
        PANTS_LOGGER.global_level.lock().replace(level);

        PANTS_LOGGER.use_color.store(use_color, Ordering::SeqCst);
        PANTS_LOGGER
          .show_rust_3rdparty_logs
          .store(show_rust_3rdparty_logs, Ordering::SeqCst);
        *PANTS_LOGGER.log_level_filters.lock() = log_levels_by_target;
        PANTS_LOGGER
          .show_target
          .store(show_target, Ordering::SeqCst);
        if set_logger(&*PANTS_LOGGER).is_err() {
          debug!("Logging already initialized.");
        }
      }
      Err(err) => panic!("Unrecognised log level from Python: {}: {}", max_level, err),
    };
  }

  /// Set up a file logger to log_file_path. Returns the file descriptor of the log file.
  #[cfg(unix)]
  pub fn set_pantsd_logger(
    &self,
    log_file_path: PathBuf,
  ) -> Result<std::os::unix::io::RawFd, String> {
    use std::os::unix::io::AsRawFd;

    {
      // Maybe close open file by dropping the existing file handle
      *self.log_file.lock() = None;
    }

    OpenOptions::new()
      .create(true)
      .append(true)
      .open(log_file_path)
      .map(|file| {
        let raw_fd = file.as_raw_fd();
        *self.log_file.lock() = Some(file);
        raw_fd
      })
      .map_err(|err| format!("Error opening pantsd logfile: {}", err))
  }

  /// log_from_python is only used in the Python FFI, which in turn is only called within the
  /// Python `NativeHandler` class. Every logging call from Python should get proxied through this
  /// function, which translates the log message into the Rust log paradigm provided by
  /// the `log` crate.
  pub fn log_from_python(message: &str, python_level: u64, target: &str) -> Result<(), String> {
    let level: PythonLogLevel = python_level.try_into().map_err(|err| format!("{}", err))?;
    log!(target: target, level.into(), "{}", message);
    Ok(())
  }

  pub fn register_stderr_handler(&self, callback: StdioHandler) -> Uuid {
    let mut handlers = self.stderr_handlers.lock();
    let unique_id = Uuid::new_v4();
    handlers.insert(unique_id, callback);
    unique_id
  }

  pub fn deregister_stderr_handler(&self, unique_id: Uuid) {
    let mut handlers = self.stderr_handlers.lock();
    handlers.remove(&unique_id);
  }
}

impl Log for PantsLogger {
  fn enabled(&self, metadata: &Metadata) -> bool {
    let global_level: LevelFilter = { *self.global_level.lock().borrow() };
    let enabled_globally = metadata.level() <= global_level;
    let log_level_filters = self.log_level_filters.lock();
    let enabled_for_target = log_level_filters
      .get(metadata.target())
      .map(|lf| metadata.level() <= *lf)
      .unwrap_or(false);

    enabled_globally || enabled_for_target
  }

  fn log(&self, record: &Record) {
    use chrono::Timelike;
    use log::Level;

    if !self.enabled(record.metadata()) {
      return;
    }

    let mut should_log = self.show_rust_3rdparty_logs.load(Ordering::SeqCst);
    if !should_log {
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

    let destination = get_destination();
    let cur_date = chrono::Local::now();
    let time_str = format!(
      "{}.{:02}",
      cur_date.format(TIME_FORMAT_STR),
      cur_date.time().nanosecond() / 10_000_000 // Two decimal places of precision.
    );

    let show_target = self.show_target.load(Ordering::SeqCst);
    let level = record.level();
    let destination_is_file = match destination {
      Destination::Pantsd => true,
      Destination::Stderr => false,
    };
    let use_color = self.use_color.load(Ordering::SeqCst) && (!destination_is_file);

    let level_marker = match level {
      _ if !use_color => format!("[{}]", level).normal().clear(),
      Level::Info => format!("[{}]", level).normal(),
      Level::Error => format!("[{}]", level).red(),
      Level::Warn => format!("[{}]", level).red(),
      Level::Debug => format!("[{}]", level).green(),
      Level::Trace => format!("[{}]", level).magenta(),
    };

    let log_string = if show_target {
      format!(
        "{} {} ({}) {}",
        time_str,
        level_marker,
        record.target(),
        record.args(),
      )
    } else {
      format!("{} {} {}", time_str, level_marker, record.args())
    };

    match destination {
      Destination::Stderr => {
        // We first try to output to all registered handlers. If there are none, or any of them
        // fail, then we fallback to sending directly to stderr.
        let handlers_map = self.stderr_handlers.lock();
        let mut any_handler_failed = false;
        for callback in handlers_map.values() {
          let handler_res = callback(&log_string);
          if handler_res.is_err() {
            any_handler_failed = true;
          }
        }
        if handlers_map.len() == 0 || any_handler_failed {
          eprintln!("{}", log_string);
        }
      }
      Destination::Pantsd => {
        let mut maybe_file = self.log_file.lock();
        if let Some(ref mut file) = *maybe_file {
          match writeln!(file, "{}", log_string) {
            Ok(()) => (),
            Err(e) => {
              eprintln!("Error writing to log file: {}", e);
            }
          }
        }
      }
    }
  }

  fn flush(&self) {}
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

impl TryFrom<&str> for Destination {
  type Error = String;
  fn try_from(dest: &str) -> Result<Self, Self::Error> {
    match dest {
      "pantsd" => Ok(Destination::Pantsd),
      "stderr" => Ok(Destination::Stderr),
      other => Err(format!("Unknown log destination: {:?}", other)),
    }
  }
}

thread_local! {
  static THREAD_DESTINATION: RefCell<Destination> = RefCell::new(Destination::Stderr)
}

task_local! {
  static TASK_DESTINATION: Destination;
}

///
/// Set the current log destination for a Thread, but _not_ for a Task. Tasks must always be spawned
/// by callers using the `scope_task_destination` helper (generally via task_executor::Executor.)
///
pub fn set_thread_destination(destination: Destination) {
  THREAD_DESTINATION.with(|thread_destination| {
    *thread_destination.borrow_mut() = destination;
  })
}

///
/// Propagate the current log destination to a Future representing a newly spawned Task. Usage of
/// this method should mostly be contained to task_executor::Executor.
///
pub async fn scope_task_destination<F>(destination: Destination, f: F) -> F::Output
where
  F: Future,
{
  TASK_DESTINATION.scope(destination, f).await
}

///
/// Get the current log destination, from either a Task or a Thread.
///
/// TODO: Having this return an Option and tracking down all cases where it has defaulted would be
/// good.
///
pub fn get_destination() -> Destination {
  if let Ok(destination) = TASK_DESTINATION.try_with(|destination| *destination) {
    destination
  } else {
    THREAD_DESTINATION.with(|destination| *destination.borrow())
  }
}
