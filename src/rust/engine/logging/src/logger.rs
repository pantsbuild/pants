// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::PythonLogLevel;

use std::collections::HashMap;
use std::convert::TryInto;
use std::fmt::Write as FmtWrite;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;

use arc_swap::ArcSwap;
use chrono::Timelike;
use colored::*;
use lazy_static::lazy_static;
use log::{debug, log, set_logger, set_max_level, Level, LevelFilter, Log, Metadata, Record};
use parking_lot::Mutex;
use regex::Regex;

const TIME_FORMAT_STR: &str = "%H:%M:%S";

lazy_static! {
    pub static ref PANTS_LOGGER: PantsLogger = PantsLogger::new();
}

struct Inner {
    per_run_logs: Mutex<Option<File>>,
    log_file: Mutex<Option<File>>,
    global_level: LevelFilter,
    show_rust_3rdparty_logs: bool,
    show_target: bool,
    log_level_filters: HashMap<String, log::LevelFilter>,
    literal_filters: Vec<String>,
    regex_filters: Vec<Regex>,
}

pub struct PantsLogger(ArcSwap<Inner>);

impl PantsLogger {
    pub fn new() -> PantsLogger {
        PantsLogger(ArcSwap::from(Arc::new(Inner {
            per_run_logs: Mutex::new(None),
            log_file: Mutex::new(None),
            global_level: LevelFilter::Off,
            show_rust_3rdparty_logs: true,
            show_target: false,
            log_level_filters: HashMap::new(),
            literal_filters: Vec::new(),
            regex_filters: Vec::new(),
        })))
    }

    pub fn init(
        max_level: u64,
        show_rust_3rdparty_logs: bool,
        show_target: bool,
        log_levels_by_target: HashMap<String, u64>,
        literal_filters: Vec<String>,
        regex_filters: Vec<Regex>,
        log_file_path: PathBuf,
    ) -> Result<(), String> {
        let log_level_filters = log_levels_by_target
            .iter()
            .map(|(k, v)| {
                let python_level: PythonLogLevel = (*v).try_into().unwrap_or_else(|e| {
                    panic!("Unrecognized log level from python: {v}: {e}");
                });
                let level: log::LevelFilter = python_level.into();
                (k.clone(), level)
            })
            .collect::<HashMap<_, _>>();

        let max_python_level: PythonLogLevel = max_level
            .try_into()
            .map_err(|e| format!("Unrecognised log level from Python: {max_level}: {e}"))?;
        let global_level: LevelFilter = max_python_level.into();

        let log_file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_file_path)
            .map_err(|err| {
                format!(
                    "Error opening pantsd logfile at '{}': {}",
                    log_file_path.display(),
                    err
                )
            })?;

        PANTS_LOGGER.0.store(Arc::new(Inner {
            per_run_logs: Mutex::default(),
            log_file: Mutex::new(Some(log_file)),
            global_level,
            show_rust_3rdparty_logs,
            show_target,
            log_level_filters,
            literal_filters,
            regex_filters,
        }));

        if set_logger(&*PANTS_LOGGER).is_err() {
            debug!("Logging already initialized.");
        }
        // TODO this should be whatever the most verbose log level specified in log_levels_by_target -
        // but I'm not sure if it's actually much of a gain over just setting this to Trace.
        set_max_level(LevelFilter::Trace);
        // We make per-destination decisions about whether to render color, and should never use
        // environment variables to decide.
        colored::control::set_override(true);
        Ok(())
    }

    pub fn set_per_run_logs(&self, per_run_log_path: Option<PathBuf>) {
        match per_run_log_path {
            None => {
                *self.0.load().per_run_logs.lock() = None;
            }
            Some(path) => {
                let file = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path)
                    .map_err(|err| format!("Error opening per-run logfile: {err}"))
                    .unwrap();
                *self.0.load().per_run_logs.lock() = Some(file);
            }
        };
    }

    /// log_from_python is only used in the Python FFI, which in turn is only called within the
    /// Python `NativeHandler` class. Every logging call from Python should get proxied through this
    /// function, which translates the log message into the Rust log paradigm provided by
    /// the `log` crate.
    pub fn log_from_python(message: &str, python_level: u64, target: &str) -> Result<(), String> {
        let level: PythonLogLevel = python_level.try_into().map_err(|err| format!("{err}"))?;
        log!(target: target, level.into(), "{}", message);
        Ok(())
    }
}

impl Log for PantsLogger {
    fn enabled(&self, metadata: &Metadata) -> bool {
        let inner = self.0.load();
        let enabled_globally = metadata.level() <= inner.global_level;
        let enabled_for_target = inner
            .log_level_filters
            .get(metadata.target())
            .map(|lf| metadata.level() <= *lf)
            .unwrap_or(false);

        enabled_globally || enabled_for_target
    }

    fn log(&self, record: &Record) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let inner = self.0.load();

        let mut should_log = inner.show_rust_3rdparty_logs;
        if !should_log {
            if let Some(module_path) = record.module_path() {
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

        let log_msg = format!("{}", record.args());
        if inner
            .literal_filters
            .iter()
            .any(|filt| log_msg.starts_with(filt))
        {
            return;
        }

        if inner.regex_filters.iter().any(|re| re.is_match(&log_msg)) {
            return;
        }

        let destination = stdio::get_destination();

        // Build the message string.
        let log_string = {
            let mut log_string = {
                let cur_date = chrono::Local::now();
                format!(
                    "{}.{:02}",
                    cur_date.format(TIME_FORMAT_STR),
                    cur_date.time().nanosecond() / 10_000_000 // Two decimal places of precision.
                )
            };

            let use_color = destination.stderr_use_color();

            let level = record.level();
            let level_marker = match level {
                _ if !use_color => format!("[{level}]").normal().clear(),
                Level::Info => format!("[{level}]").normal(),
                Level::Error => format!("[{level}]").red(),
                Level::Warn => format!("[{level}]").yellow(),
                Level::Debug => format!("[{level}]").green(),
                Level::Trace => format!("[{level}]").magenta(),
            };
            write!(log_string, " {level_marker}").unwrap();

            if inner.show_target {
                write!(log_string, " ({})", record.target()).unwrap();
            };
            writeln!(log_string, " {log_msg}").unwrap();
            log_string
        };
        let log_bytes = log_string.as_bytes();

        {
            let mut maybe_per_run_file = inner.per_run_logs.lock();
            if let Some(ref mut file) = *maybe_per_run_file {
                // deliberately ignore errors writing to per-run log file
                let _ = file.write_all(log_bytes);
            }
        }

        // Attempt to write to stdio, and write to the pantsd log if we fail (either because we don't
        // have a valid stdio instance, or because of an error).
        if destination.write_stderr_raw(log_bytes).is_err() {
            let mut maybe_file = inner.log_file.lock();
            if let Some(ref mut file) = *maybe_file {
                match file.write_all(log_bytes) {
                    Ok(()) => (),
                    Err(e) => {
                        // If we've failed to write to stdio, but also to our log file, our only recourse is to
                        // try to write to a different file.
                        fatal_log!("Failed to write to log file {:?}: {}", file, e);
                    }
                }
            }
        }
    }

    fn flush(&self) {}
}
