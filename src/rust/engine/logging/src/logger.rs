// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::PythonLogLevel;

use std::cell::RefCell;
use std::collections::HashMap;
use std::convert::TryInto;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};

use colored::*;
use lazy_static::lazy_static;
use log::{debug, log, set_logger, set_max_level, LevelFilter, Log, Metadata, Record};
use parking_lot::Mutex;
use regex::Regex;

const TIME_FORMAT_STR: &str = "%H:%M:%S";

lazy_static! {
  pub static ref PANTS_LOGGER: PantsLogger = PantsLogger::new();
}

// TODO: The non-atomic portions of this struct should likely be composed into a single RwLock.
pub struct PantsLogger {
  per_run_logs: Mutex<Option<File>>,
  log_file: Mutex<Option<File>>,
  global_level: Mutex<RefCell<LevelFilter>>,
  use_color: AtomicBool,
  show_rust_3rdparty_logs: AtomicBool,
  show_target: AtomicBool,
  log_level_filters: Mutex<HashMap<String, log::LevelFilter>>,
  message_regex_filters: Mutex<Vec<Regex>>,
}

impl PantsLogger {
  pub fn new() -> PantsLogger {
    PantsLogger {
      per_run_logs: Mutex::new(None),
      log_file: Mutex::new(None),
      global_level: Mutex::new(RefCell::new(LevelFilter::Off)),
      show_rust_3rdparty_logs: AtomicBool::new(true),
      use_color: AtomicBool::new(false),
      show_target: AtomicBool::new(false),
      log_level_filters: Mutex::new(HashMap::new()),
      message_regex_filters: Mutex::new(Vec::new()),
    }
  }

  pub fn init(
    max_level: u64,
    show_rust_3rdparty_logs: bool,
    use_color: bool,
    show_target: bool,
    log_levels_by_target: HashMap<String, u64>,
    message_regex_filters: Vec<Regex>,
    log_file_path: PathBuf,
  ) -> Result<(), String> {
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

    let max_python_level: PythonLogLevel = max_level
      .try_into()
      .map_err(|e| format!("Unrecognised log level from Python: {}: {}", max_level, e))?;
    let level: LevelFilter = max_python_level.into();

    // TODO this should be whatever the most verbose log level specified in log_domain_levels -
    // but I'm not sure if it's actually much of a gain over just setting this to Trace.
    set_max_level(LevelFilter::Trace);
    PANTS_LOGGER.global_level.lock().replace(level);

    PANTS_LOGGER.use_color.store(use_color, Ordering::SeqCst);
    PANTS_LOGGER
      .show_rust_3rdparty_logs
      .store(show_rust_3rdparty_logs, Ordering::SeqCst);
    *PANTS_LOGGER.log_level_filters.lock() = log_levels_by_target;
    *PANTS_LOGGER.message_regex_filters.lock() = message_regex_filters;
    PANTS_LOGGER
      .show_target
      .store(show_target, Ordering::SeqCst);
    *PANTS_LOGGER.log_file.lock() = {
      let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_file_path)
        .map_err(|err| format!("Error opening pantsd logfile: {}", err))?;
      Some(log_file)
    };

    if set_logger(&*PANTS_LOGGER).is_err() {
      debug!("Logging already initialized.");
    }
    Ok(())
  }

  pub fn set_per_run_logs(&self, per_run_log_path: Option<PathBuf>) {
    match per_run_log_path {
      None => {
        *self.per_run_logs.lock() = None;
      }
      Some(path) => {
        let file = OpenOptions::new()
          .create(true)
          .append(true)
          .open(path)
          .map_err(|err| format!("Error opening per-run logfile: {}", err))
          .unwrap();
        *self.per_run_logs.lock() = Some(file);
      }
    };
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

    let cur_date = chrono::Local::now();
    let time_str = format!(
      "{}.{:02}",
      cur_date.format(TIME_FORMAT_STR),
      cur_date.time().nanosecond() / 10_000_000 // Two decimal places of precision.
    );

    let show_target = self.show_target.load(Ordering::SeqCst);
    let level = record.level();
    // TODO: Fix application of color for log-files.
    let use_color = self.use_color.load(Ordering::SeqCst);

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
        "{} {} ({}) {}\n",
        time_str,
        level_marker,
        record.target(),
        record.args(),
      )
    } else {
      format!("{} {} {}\n", time_str, level_marker, record.args())
    };

    {
      let message_regex_filters = self.message_regex_filters.lock();
      if message_regex_filters
        .iter()
        .any(|re| re.is_match(&log_string))
      {
        return;
      }
    }

    let log_bytes = log_string.as_bytes();

    {
      let mut maybe_per_run_file = self.per_run_logs.lock();
      if let Some(ref mut file) = *maybe_per_run_file {
        // deliberately ignore errors writing to per-run log file
        let _ = file.write_all(log_bytes);
      }
    }

    // Attempt to write to stdio, and write to the pantsd log if we fail (either because we don't
    // have a valid stdio instance, or because of an error).
    let destination = stdio::get_destination();
    if stdio::Destination::write_stderr_raw(&destination, log_bytes).is_err() {
      let mut maybe_file = self.log_file.lock();
      if let Some(ref mut file) = *maybe_file {
        match file.write_all(log_bytes) {
          Ok(()) => (),
          Err(e) => {
            // If we've failed to write to stdio, but also to our log file, our only recourse is to
            // try to write to a different file.
            debug_log!("fatal.log", "Failed to write to log file {:?}: {}", file, e);
          }
        }
      }
    }
  }

  fn flush(&self) {}
}
