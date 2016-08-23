use libc;

use std::ffi::CString;

use core::{Digest, Key, TypeId};

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

pub struct FixedBuffer {
  buf: [u8;256],
}

pub type ToStrExtern =
  extern "C" fn(*const StorageExtern, *const Digest, *mut FixedBuffer) -> u8;

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
    // Create a buffer with a maximum length.
    let mut buffer = FixedBuffer { buf: [0;256] };
    let len = (self.to_str)(self.storage, digest, &mut buffer) as usize;
    // Trim the buffer content to the reported written length, and decode.
    let mut trimmed = buffer.buf.to_vec();
    trimmed.truncate(len);
    // Attempt to decode from unicode.
    String::from_utf8(trimmed).unwrap_or_else(|e| {
      format!("<failed to decode unicode for {:?}: {}>", digest, e)
    })
  }
}
