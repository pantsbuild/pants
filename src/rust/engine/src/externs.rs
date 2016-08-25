use libc;

use std::mem;

use core::{Digest, Field, Key, TypeId};

// An opaque pointer to a context used by the extern functions.
pub type ExternContext = libc::c_void;

pub type IsInstanceExtern =
  extern "C" fn(*const ExternContext, *const Key, *const TypeId) -> bool;

pub struct IsInstanceFunction {
  isinstance: IsInstanceExtern,
  context: *const ExternContext,
}

impl IsInstanceFunction {
  pub fn new(isinstance: IsInstanceExtern, context: *const ExternContext) -> IsInstanceFunction {
    IsInstanceFunction {
      isinstance: isinstance,
      context: context,
    }
  }

  pub fn call(&self, key: &Key, type_id: &TypeId) -> bool {
    (self.isinstance)(self.context, key, type_id)
  }
}

pub type StoreListExtern =
  extern "C" fn(*const ExternContext, *const Key, u64) -> Key;

pub struct StoreListFunction {
  store_list: StoreListExtern,
  context: *const ExternContext,
}

impl StoreListFunction {
  pub fn new(store_list: StoreListExtern, context: *const ExternContext) -> StoreListFunction {
    StoreListFunction {
      store_list: store_list,
      context: context,
    }
  }

  pub fn call(&self, keys: Vec<&Key>) -> Key {
    let keys_clone: Vec<Key> = keys.into_iter().map(|&k| k).collect();
    (self.store_list)(self.context, keys_clone.as_ptr(), keys_clone.len() as u64)
  }
}

pub type ProjectExtern =
  extern "C" fn(*const ExternContext, *const Key, *const Field, *const TypeId) -> Key;

pub struct ProjectFunction {
  project: ProjectExtern,
  context: *const ExternContext,
}

impl ProjectFunction {
  pub fn new(project: ProjectExtern, context: *const ExternContext) -> ProjectFunction {
    ProjectFunction {
      project: project,
      context: context,
    }
  }

  pub fn call(&self, key: &Key, field: &Field, type_id: &TypeId) -> Key {
    (self.project)(self.context, key, field, type_id)
  }
}

#[repr(C)]
pub struct KeyBuffer {
  keys_ptr: *mut Key,
  keys_len: u64,
}

pub type ProjectMultiExtern =
  extern "C" fn(*const ExternContext, *const Key, *const Field) -> KeyBuffer;

pub struct ProjectMultiFunction {
  project_multi: ProjectMultiExtern,
  context: *const ExternContext,
}

impl ProjectMultiFunction {
  pub fn new(project_multi: ProjectMultiExtern, context: *const ExternContext) -> ProjectMultiFunction {
    ProjectMultiFunction {
      project_multi: project_multi,
      context: context,
    }
  }

  pub fn call(&self, key: &Key, field: &Field) -> Vec<Key> {
    let buf = (self.project_multi)(self.context, key, field);
    let keys = with_vec(buf.keys_ptr, buf.keys_len as usize, |key_vec| key_vec.clone());
    keys
  }
}

#[repr(C)]
pub struct UTF8Buffer {
  str_ptr: *mut u8,
  str_len: u64,
}

pub type ToStrExtern =
  extern "C" fn(*const ExternContext, *const Digest) -> UTF8Buffer;

pub struct ToStrFunction {
  to_str: ToStrExtern,
  context: *const ExternContext,
}

impl ToStrFunction {
  pub fn new(to_str: ToStrExtern, context: *const ExternContext) -> ToStrFunction {
    ToStrFunction {
      to_str: to_str,
      context: context,
    }
  }

  pub fn call(&self, digest: &Digest) -> String {
    let buf = (self.to_str)(self.context, digest);
    let str =
      with_vec(buf.str_ptr, buf.str_len as usize, |char_vec| {
        // Attempt to decode from unicode.
        String::from_utf8(char_vec.clone()).unwrap_or_else(|e| {
          format!("<failed to decode unicode for {:?}: {}>", digest, e)
        })
      });
    str
  }
}

pub fn with_vec<F,C,T>(c_ptr: *mut C, c_len: usize, f: F) -> T
    where F: FnOnce(&Vec<C>)->T {
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  mem::forget(cs);
  output
}
