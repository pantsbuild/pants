use libc;

use std::ffi::CString;
use std::mem;

use core::{Digest, Field, Key, TypeId};

pub type StorageExtern = libc::c_void;

pub type IsInstanceExtern =
  extern "C" fn(*const StorageExtern, *const Key, *const TypeId) -> bool;

pub struct IsInstanceFunction {
  isinstance: IsInstanceExtern,
  storage: *const StorageExtern,
}

impl IsInstanceFunction {
  pub fn new(isinstance: IsInstanceExtern, storage: *const StorageExtern) -> IsInstanceFunction {
    IsInstanceFunction {
      isinstance: isinstance,
      storage: storage,
    }
  }

  pub fn call(&self, key: &Key, type_id: &TypeId) -> bool {
    (self.isinstance)(self.storage, key, type_id)
  }
}

pub type StoreListExtern =
  extern "C" fn(*const StorageExtern, *const Key, u64) -> Key;

pub struct StoreListFunction {
  store_list: StoreListExtern,
  storage: *const StorageExtern,
}

impl StoreListFunction {
  pub fn new(store_list: StoreListExtern, storage: *const StorageExtern) -> StoreListFunction {
    StoreListFunction {
      store_list: store_list,
      storage: storage,
    }
  }

  pub fn call(&self, keys: Vec<&Key>) -> Key {
    let keys_clone: Vec<Key> = keys.into_iter().map(|&k| k).collect();
    (self.store_list)(self.storage, keys_clone.as_ptr(), keys_clone.len() as u64)
  }
}

pub struct KeyBuffer {
  keys_ptr: *mut Key,
  keys_len: u64,
  keys_cap: u64,
}

pub type ProjectMultiExtern =
  extern "C" fn(*const StorageExtern, *const Key, *const Field) -> *mut KeyBuffer;

pub struct ProjectMultiFunction {
  project_multi: ProjectMultiExtern,
  storage: *const StorageExtern,
}

impl ProjectMultiFunction {
  pub fn new(project_multi: ProjectMultiExtern, storage: *const StorageExtern) -> ProjectMultiFunction {
    ProjectMultiFunction {
      project_multi: project_multi,
      storage: storage,
    } 
  }

  pub fn call(&self, key: &Key, field: &Field) -> Vec<Key> {
    let buf = unsafe { &*(self.project_multi)(self.storage, key, field) };
    let keys = with_vec(buf.keys_ptr, buf.keys_len as usize, |key_vec| key_vec.clone());
    // This isn't ours: forget about it!
    mem::forget(buf);
    keys
  }
}

pub struct UTF8Buffer {
  str_ptr: *mut u8,
  str_len: u64,
  str_cap: u64,
}

pub type ToStrExtern =
  extern "C" fn(*const StorageExtern, *const Digest) -> *mut UTF8Buffer;

pub struct ToStrFunction {
  to_str: ToStrExtern,
  storage: *const StorageExtern,
}

impl ToStrFunction {
  pub fn new(to_str: ToStrExtern, storage: *const StorageExtern) -> ToStrFunction {
    ToStrFunction {
      to_str: to_str,
      storage: storage,
    }
  }

  pub fn call(&self, digest: &Digest) -> String {
    let buf = unsafe { &*(self.to_str)(self.storage, digest) };
    let str =
      with_vec(buf.str_ptr, buf.str_len as usize, |char_vec| {
        // Attempt to decode from unicode.
        String::from_utf8(char_vec.clone()).unwrap_or_else(|e| {
          format!("<failed to decode unicode for {:?}: {}>", digest, e)
        })
      });
    // This isn't ours: forget about it!
    mem::forget(buf);
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
