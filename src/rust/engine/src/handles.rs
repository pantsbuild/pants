// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::os::raw;

use externs;
use parking_lot::Mutex;

pub type RawHandle = *const raw::c_void;

///
/// Represents a handle to a python object, explicitly without equality or hashing. Whenever
/// the equality/identity of a Value matters, a Key should be computed for it and used instead.
///
/// Handle implements Clone by calling out to a python extern `clone_val` which clones the
/// underlying CFFI handle.
///
#[repr(C)]
pub struct Handle(RawHandle);

impl Handle {
  ///
  /// An escape hatch to allow for cloning a Handle without cloning the value it points to. You
  /// should generally not do this unless you are certain the input Handle has been mem::forgotten
  /// (otherwise it will be `Drop`ed twice).
  ///
  pub unsafe fn clone_shallow(&self) -> Handle {
    Handle(self.0)
  }
}

impl PartialEq for Handle {
  fn eq(&self, other: &Handle) -> bool {
    externs::equals(self, other)
  }
}

impl Eq for Handle {}

impl Drop for Handle {
  fn drop(&mut self) {
    DROPPING_HANDLES.lock().push(DroppingHandle(self.0));
  }
}

// By default, a Handle would not be marked Send because of the raw pointer it holds.
// Because Python objects are threadsafe, we can safely implement Send.
unsafe impl Send for Handle {}
unsafe impl Sync for Handle {}

const MIN_DRAIN_HANDLES: usize = 256;

///
/// A Handle that is currently being dropped. This wrapper exists to mark the pointer Send.
///
#[repr(C)]
pub struct DroppingHandle(RawHandle);

unsafe impl Send for DroppingHandle {}

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
  static ref DROPPING_HANDLES: Mutex<Vec<DroppingHandle>> = Mutex::new(Vec::new());
}

///
/// If an appreciable number of Handles have been queued, drop them.
///
pub fn maybe_drop_handles() {
  let handles: Option<Vec<_>> = {
    let mut q = DROPPING_HANDLES.lock();
    if q.len() > MIN_DRAIN_HANDLES {
      Some(q.drain(..).collect::<Vec<_>>())
    } else {
      None
    }
  };
  if let Some(handles) = handles {
    externs::drop_handles(&handles);
  }
}
