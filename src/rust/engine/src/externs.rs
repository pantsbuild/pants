use std::collections::HashMap;
use std::mem;
use std::os::raw;
use std::string::FromUtf8Error;
use std::sync::RwLock;

use core::{Field, Function, Id, Key, TypeConstraint, TypeId, Value};
use nodes::Runnable;
use handles::Handle;

// An opaque pointer to a context used by the extern functions.
pub type ExternContext = raw::c_void;

pub type SatisfiedByExtern =
  extern "C" fn(*const ExternContext, *const TypeConstraint, *const TypeId) -> bool;

pub struct Externs {
  context: *const ExternContext,
  key_for: KeyForExtern,
  val_for: ValForExtern,
  clone_val: CloneValExtern,
  drop_handles: DropHandlesExtern,
  satisfied_by: SatisfiedByExtern,
  satisfied_by_cache: RwLock<HashMap<(TypeConstraint, TypeId), bool>>,
  store_list: StoreListExtern,
  project: ProjectExtern,
  project_multi: ProjectMultiExtern,
  id_to_str: IdToStrExtern,
  val_to_str: ValToStrExtern,
  create_exception: CreateExceptionExtern,
  invoke_runnable: InvokeRunnable,
}

// The pointer to the context is safe for sharing between threads.
unsafe impl Sync for Externs {}
unsafe impl Send for Externs {}

impl Externs {
  pub fn new(
    ext_context: *const ExternContext,
    key_for: KeyForExtern,
    val_for: ValForExtern,
    clone_val: CloneValExtern,
    drop_handles: DropHandlesExtern,
    id_to_str: IdToStrExtern,
    val_to_str: ValToStrExtern,
    satisfied_by: SatisfiedByExtern,
    store_list: StoreListExtern,
    project: ProjectExtern,
    project_multi: ProjectMultiExtern,
    create_exception: CreateExceptionExtern,
    invoke_runnable: InvokeRunnable,
  ) -> Externs {
    Externs {
      context: ext_context,
      key_for: key_for,
      val_for: val_for,
      clone_val: clone_val,
      drop_handles: drop_handles,
      satisfied_by: satisfied_by,
      satisfied_by_cache: RwLock::new(HashMap::new()),
      store_list: store_list,
      project: project,
      project_multi: project_multi,
      id_to_str: id_to_str,
      val_to_str: val_to_str,
      create_exception: create_exception,
      invoke_runnable: invoke_runnable,
    }
  }

  pub fn key_for(&self, val: &Value) -> Key {
    (self.key_for)(self.context, val)
  }

  pub fn val_for(&self, key: &Key) -> Value {
    (self.val_for)(self.context, key)
  }

  pub fn clone_val(&self, val: &Value) -> Value {
    (self.clone_val)(self.context, val)
  }

  pub fn drop_handles(&self, handles: Vec<Handle>) {
    (self.drop_handles)(self.context, handles.as_ptr(), handles.len() as u64)
  }

  pub fn satisfied_by(&self, constraint: &TypeConstraint, cls: &TypeId) -> bool {
    let key = (*constraint, *cls);

    // See if a value already exists.
    {
      let read = self.satisfied_by_cache.read().unwrap();
      if let Some(v) = read.get(&key) {
        return *v;
      }
    }

    // If not, compute and insert.
    let mut write = self.satisfied_by_cache.write().unwrap();
    write.entry(key)
      .or_insert_with(||
        (self.satisfied_by)(self.context, constraint, cls)
      )
      .clone()
  }

  pub fn store_list(&self, values: Vec<&Value>, merge: bool) -> Value {
    let values_clone: Vec<*const Value> = values.into_iter().map(|v| v as *const Value).collect();
    (self.store_list)(self.context, values_clone.as_ptr(), values_clone.len() as u64, merge)
  }

  pub fn project(&self, value: &Value, field: &Field, type_id: &TypeId) -> Value {
    (self.project)(self.context, value, field, type_id)
  }

  pub fn project_multi(&self, value: &Value, field: &Field) -> Vec<Value> {
    let buf = (self.project_multi)(self.context, value, field);
    with_vec(buf.values_ptr, buf.values_len as usize, |value_vec| {
      unsafe {
        value_vec.iter().map(|v| v.clone()).collect()
      }
    })
  }

  pub fn id_to_str(&self, digest: Id) -> String {
    (self.id_to_str)(self.context, digest).to_string().unwrap_or_else(|e| {
      format!("<failed to decode unicode for {:?}: {}>", digest, e)
    })
  }

  pub fn val_to_str(&self, val: &Value) -> String {
    (self.val_to_str)(self.context, val).to_string().unwrap_or_else(|e| {
      format!("<failed to decode unicode for {:?}: {}>", val, e)
    })
  }

  pub fn create_exception(&self, msg: &str) -> Value {
    (self.create_exception)(self.context, msg.as_ptr(), msg.len() as u64)
  }

  pub fn invoke_runnable(&self, runnable: &Runnable) -> Result<Value, Value> {
    let result =
      (self.invoke_runnable)(
        self.context,
        &runnable.func,
        runnable.args.as_ptr(),
        runnable.args.len() as u64,
        runnable.cacheable
      );
    if result.is_throw {
      Err(result.value)
    } else {
      Ok(result.value)
    }
  }
}

pub type KeyForExtern =
  extern "C" fn(*const ExternContext, *const Value) -> Key;

pub type ValForExtern =
  extern "C" fn(*const ExternContext, *const Key) -> Value;

pub type CloneValExtern =
  extern "C" fn(*const ExternContext, *const Value) -> Value;

pub type DropHandlesExtern =
  extern "C" fn(*const ExternContext, *const Handle, u64);

pub type StoreListExtern =
  extern "C" fn(*const ExternContext, *const *const Value, u64, bool) -> Value;

pub type ProjectExtern =
  extern "C" fn(*const ExternContext, *const Value, *const Field, *const TypeId) -> Value;

#[repr(C)]
#[derive(Debug)]
pub struct RunnableComplete {
  pub value: Value,
  pub is_throw: bool,
}

#[repr(C)]
pub struct ValueBuffer {
  values_ptr: *mut Value,
  values_len: u64,
}

pub type ProjectMultiExtern =
  extern "C" fn(*const ExternContext, *const Value, *const Field) -> ValueBuffer;

#[repr(C)]
pub struct UTF8Buffer {
  str_ptr: *mut u8,
  str_len: u64,
}

impl UTF8Buffer {
  pub fn to_string(&self) -> Result<String, FromUtf8Error> {
    with_vec(self.str_ptr, self.str_len as usize, |char_vec| {
      // Attempt to decode from unicode.
      String::from_utf8(char_vec.clone())
    })
  }
}

pub type IdToStrExtern =
  extern "C" fn(*const ExternContext, Id) -> UTF8Buffer;

pub type ValToStrExtern =
  extern "C" fn(*const ExternContext, *const Value) -> UTF8Buffer;

pub type CreateExceptionExtern =
  extern "C" fn(*const ExternContext, str_ptr: *const u8, str_len: u64) -> Value;

pub type InvokeRunnable =
  extern "C" fn(*const ExternContext, *const Function, *const Value, u64, bool) -> RunnableComplete;

pub fn with_vec<F, C, T>(c_ptr: *mut C, c_len: usize, f: F) -> T
    where F: FnOnce(&Vec<C>)->T {
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  mem::forget(cs);
  output
}
