use std::collections::VecDeque;
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
 */
lazy_static! {
  static ref DROPPED_HANDLES: Mutex<VecDeque<SendableHandle>> = Mutex::new(VecDeque::new());
}

pub fn drop_handle(handle: Handle) {
  DROPPED_HANDLES.lock().unwrap().push_back(SendableHandle(handle));
}
