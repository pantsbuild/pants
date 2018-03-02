// This file creates the unmangled symbol initnative_engine which cffi will use as the entry point
// to this shared library.
//
// It calls the extern'd wrapped_initnative_engine (generated in
// src/rust/engine/src/cffi/native_engine.c by build-support/native-engine/bootstrap_cffi.py).
// This is a bit awkward and fiddly, but necessary because rust doesn't currently have a way to
// re-export symbols from C libraries, other than this.
// See https://github.com/rust-lang/rust/issues/36342

extern "C" {
  pub fn wrapped_initnative_engine();
}

#[no_mangle]
pub extern "C" fn initnative_engine() {
  unsafe { wrapped_initnative_engine() }
}
