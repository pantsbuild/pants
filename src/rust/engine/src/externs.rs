use libc;

use core::{Key, TypeId};

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

  pub fn isinstance(&self, key: &Key, type_id: &TypeId) -> bool {
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

  pub fn store_list(&self, keys: Vec<&Key>) -> Key {
    let keys_clone: Vec<Key> = keys.into_iter().map(|&k| k).collect();
    (self.store_list)(self.storage, keys_clone.as_ptr(), keys_clone.len() as u64)
  }
}
