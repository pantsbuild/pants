// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::os::raw;
use std::sync::Mutex;

pub type Handle = *const raw::c_void;

const MIN_DRAIN_HANDLES: usize = 256;

// A sendable wrapper around a Handle.
struct SendableHandle(Handle);

unsafe impl Send for SendableHandle {}

///
/// A static queue of Handles which used to be owned by `Value`s. When a Value is dropped, its
/// Handle is added to this queue. Some thread with access to the ExternContext should periodically
/// consume this queue to drop the relevant handles on the python side.
///
/// This queue avoids giving every `Value` a reference to the ExternContext, which would allow them
/// to drop themselves directly, but would increase their size.
///
/// TODO: This queue should likely move to `core` to allow `enqueue` to be private.
///
lazy_static! {
  static ref DROPPING_HANDLES: Mutex<Vec<SendableHandle>> = Mutex::new(Vec::new());
}

///
/// Enqueue a handle to be dropped.
///
pub fn enqueue_drop_handle(handle: Handle) {
  DROPPING_HANDLES.lock().unwrap().push(SendableHandle(handle));
}

///
/// If an appreciable number of Handles have been queued, drain them.
///
pub fn maybe_drain_handles() -> Option<Vec<Handle>> {
  let mut q = DROPPING_HANDLES.lock().unwrap();
  if q.len() > MIN_DRAIN_HANDLES {
    let handles: Vec<_> = q.drain(..).collect();
    Some(handles.iter().map(|sh| sh.0).collect())
  } else {
    None
  }
}
