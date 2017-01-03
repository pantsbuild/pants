use std::os::raw;
use std::sync::Mutex;

pub type Handle = *const raw::c_void;

// A sendable wrapper around a Handle.
struct SendableHandle(Handle);

unsafe impl Send for SendableHandle {}

/**
 * A static queue of Handles which used to be owned by `Value`s. When a Value is dropped, its
 * Handle is added to this queue. Some thread with access to the ExternContext should periodically
 * consume this queue to drop the relevant handles on the python side.
 *
 * This queue avoids giving every `Value` a reference to the ExternContext, which would allow them
 * to drop themselves directly, but would increase their size.
 *
 * TODO: This queue should likely move to `core` to allow `enqueue` to be private.
 */
lazy_static! {
  static ref DROPPING_HANDLES: Mutex<Vec<SendableHandle>> = Mutex::new(Vec::new());
}

/**
 * Enqueue a handle to be dropped.
 */
pub fn enqueue_drop_handle(handle: Handle) {
  DROPPING_HANDLES.lock().unwrap().push(SendableHandle(handle));
}

/**
 * Take all Handles that have been queued to be dropped.
 */
pub fn drain_handles() -> Vec<Handle> {
  let mut q = DROPPING_HANDLES.lock().unwrap();
  let handles: Vec<_> = q.drain(..).collect();
  handles.iter().map(|sh| sh.0).collect()
}
