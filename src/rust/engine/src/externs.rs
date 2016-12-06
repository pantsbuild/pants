use libc;

use std::cell::RefCell;
use std::collections::HashMap;
use std::mem;
use std::string::FromUtf8Error;

use core::{Field, Function, Id, Key, RunnableComplete, TypeConstraint, TypeId, Value};
use nodes::Runnable;

// An opaque pointer to a context used by the extern functions.
pub type ExternContext = libc::c_void;

pub type SatisfiedByExtern =
  extern "C" fn(*const ExternContext, *const TypeConstraint, *const TypeId) -> bool;

#[derive(Clone)]
pub struct Externs {
  context: *const ExternContext,
  key_for: KeyForExtern,
  satisfied_by: SatisfiedByExtern,
  satisfied_by_cache: RefCell<HashMap<(TypeConstraint, TypeId), bool>>,
  store_list: StoreListExtern,
  project: ProjectExtern,
  project_multi: ProjectMultiExtern,
  id_to_str: IdToStrExtern,
  val_to_str: ValToStrExtern,
  create_exception: CreateExceptionExtern,
  invoke_runnable: InvokeRunnable,
}

impl Externs {
  pub fn new(
    ext_context: *const ExternContext,
    key_for: KeyForExtern,
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
      satisfied_by: satisfied_by,
      satisfied_by_cache: RefCell::new(HashMap::new()),
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

  pub fn satisfied_by(&self, constraint: &TypeConstraint, cls: &TypeId) -> bool {
    self.satisfied_by_cache.borrow_mut().entry((*constraint, *cls))
      .or_insert_with(||
        (self.satisfied_by)(self.context, constraint, cls)
      )
      .clone()
  }

  pub fn store_list(&self, values: Vec<&Value>, merge: bool) -> Value {
    if merge && values.len() == 1 {
      // We're merging, but there is only one input value: return it immediately.
      if let Some(&first) = values.first() {
        return first.clone();
      }
    }

    // Execute extern.
    let values_clone: Vec<Value> = values.into_iter().map(|&v| v).collect();
    (self.store_list)(self.context, values_clone.as_ptr(), values_clone.len() as u64, merge)
  }

  pub fn project(&self, value: &Value, field: &Field, type_id: &TypeId) -> Value {
    (self.project)(self.context, value, field, type_id)
  }

  pub fn project_multi(&self, value: &Value, field: &Field) -> Vec<Value> {
    let buf = (self.project_multi)(self.context, value, field);
    with_vec(buf.values_ptr, buf.values_len as usize, |value_vec| value_vec.clone())
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

  pub fn create_exception(&self, msg: String) -> Value {
    (self.create_exception)(self.context, msg.as_ptr(), msg.len() as u64)
  }

  pub fn invoke_runnable(&self, runnable: &Runnable) -> RunnableComplete {
    let args_clone: Vec<Value> = runnable.args().clone();
    (self.invoke_runnable)(
      self.context, runnable.func(), args_clone.as_ptr(), args_clone.len() as u64, runnable.cacheable())
  }
}

pub type KeyForExtern =
  extern "C" fn(*const ExternContext, *const Value) -> Key;

pub type StoreListExtern =
  extern "C" fn(*const ExternContext, *const Value, u64, bool) -> Value;

pub type ProjectExtern =
  extern "C" fn(*const ExternContext, *const Value, *const Field, *const TypeId) -> Value;

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
