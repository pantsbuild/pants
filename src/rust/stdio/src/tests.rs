// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::PathBuf;
use std::sync::Arc;

use crate::{Destination, InnerDestination, get_destination, set_thread_destination};

#[test]
fn per_run_log_is_destination_scoped() {
    let tempdir = tempfile::tempdir().unwrap();
    let path_one = tempdir.path().join("one.log");
    let path_two = tempdir.path().join("two.log");

    let write_via_thread = |path: PathBuf, content: &'static [u8]| {
        std::thread::spawn(move || {
            set_thread_destination(Arc::new(Destination::new(InnerDestination::Logging)));
            get_destination().set_per_run_log_path(Some(path)).unwrap();
            get_destination().write_per_run_log(content);
        })
        .join()
        .unwrap()
    };

    write_via_thread(path_one.clone(), b"one");
    write_via_thread(path_two.clone(), b"two");

    assert_eq!(std::fs::read(&path_one).unwrap(), b"one");
    assert_eq!(std::fs::read(&path_two).unwrap(), b"two");
}

#[test]
fn per_run_log_ignores_writes_when_unset() {
    let destination = Destination::new(InnerDestination::Logging);
    destination.write_per_run_log(b"dropped");
}

#[test]
fn per_run_log_cleared_by_none() {
    let tempdir = tempfile::tempdir().unwrap();
    let path = tempdir.path().join("run.log");

    let destination = Destination::new(InnerDestination::Logging);
    destination
        .set_per_run_log_path(Some(path.clone()))
        .unwrap();
    destination.write_per_run_log(b"kept");
    destination.set_per_run_log_path(None).unwrap();
    destination.write_per_run_log(b"dropped");

    assert_eq!(std::fs::read(&path).unwrap(), b"kept");
}

#[test]
fn console_clear_clears_per_run_log() {
    let tempdir = tempfile::tempdir().unwrap();
    let path = tempdir.path().join("run.log");

    let destination = Destination::new(InnerDestination::Logging);
    destination
        .set_per_run_log_path(Some(path.clone()))
        .unwrap();
    destination.write_per_run_log(b"kept");
    destination.console_clear();
    destination.write_per_run_log(b"dropped");

    assert_eq!(std::fs::read(&path).unwrap(), b"kept");
}
