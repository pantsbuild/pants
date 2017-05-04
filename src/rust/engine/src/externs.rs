// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::ffi::OsString;
use std::mem;
use std::os::raw;
use std::os::unix::ffi::OsStringExt;
use std::string::FromUtf8Error;
use std::sync::RwLock;

use core::{Failure, Function, Id, Key, TypeConstraint, TypeId, Value};
use handles::Handle;


pub fn log(level: LogLevel, msg: &str) {
  with_externs(|e|
    (e.log)(e.context, level as u8, msg.as_ptr(), msg.len() as u64)
  )
}

pub fn key_for(val: &Value) -> Key {
  with_externs(|e|
    (e.key_for)(e.context, val)
  )
}

pub fn val_for(key: &Key) -> Value {
  with_externs(|e|
    (e.val_for)(e.context, key)
  )
}

pub fn clone_val(val: &Value) -> Value {
  with_externs(|e|
    (e.clone_val)(e.context, val)
  )
}

pub fn val_for_id(id: Id) -> Value {
  val_for(&Key::new_with_anon_type_id(id))
}

pub fn drop_handles(handles: Vec<Handle>) {
  with_externs(|e|
    (e.drop_handles)(e.context, handles.as_ptr(), handles.len() as u64)
  )
}

pub fn satisfied_by(constraint: &TypeConstraint, obj: &Value) -> bool {
  with_externs(|e| {
    (e.satisfied_by)(e.context, constraint, obj)
  })
}

pub fn satisfied_by_type(constraint: &TypeConstraint, cls: &TypeId) -> bool {
  with_externs(|e| {
    let key = (*constraint, *cls);

    // See if a value already exists.
    {
      let read = e.satisfied_by_type_cache.read().unwrap();
      if let Some(v) = read.get(&key) {
        return *v;
      }
    }

    // If not, compute and insert.
    let mut write = e.satisfied_by_type_cache.write().unwrap();
    write.entry(key)
      .or_insert_with(||
        (e.satisfied_by_type)(e.context, constraint, cls)
      )
      .clone()
  })
}

pub fn store_list(values: Vec<&Value>, merge: bool) -> Value {
  with_externs(|e| {
    let values_clone: Vec<*const Value> = values.into_iter().map(|v| v as *const Value).collect();
    (e.store_list)(e.context, values_clone.as_ptr(), values_clone.len() as u64, merge)
  })
}

pub fn store_bytes(bytes: &[u8]) -> Value {
  with_externs(|e|
    (e.store_bytes)(e.context, bytes.as_ptr(), bytes.len() as u64)
  )
}

pub fn project(value: &Value, field: &str, type_id: &TypeId) -> Value {
  with_externs(|e|
    (e.project)(e.context, value, field.as_ptr(), field.len() as u64, type_id)
  )
}

pub fn project_ignoring_type(value: &Value, field: &str) -> Value {
  with_externs(|e|
    (e.project_ignoring_type)(e.context, value, field.as_ptr(), field.len() as u64)
  )
}

pub fn project_multi(value: &Value, field: &str) -> Vec<Value> {
  with_externs(|e| {
    (e.project_multi)(e.context, value, field.as_ptr(), field.len() as u64).to_vec()
  })
}

pub fn project_multi_strs(item: &Value, field: &str) -> Vec<String> {
  project_multi(item, field).iter()
    .map(|v| val_to_str(v))
    .collect()
}

pub fn project_str(value: &Value, field: &str) -> String {
  let name_val =
    with_externs(|e|
      (e.project)(e.context, value, field.as_ptr(), field.len() as u64, &e.py_str_type)
    );
  val_to_str(&name_val)
}

pub fn key_to_str(key: &Key) -> String {
  val_to_str(&val_for(key))
}

pub fn id_to_str(digest: Id) -> String {
  with_externs(|e| {
    (e.id_to_str)(e.context, digest).to_string().unwrap_or_else(|e| {
      format!("<failed to decode unicode for {:?}: {}>", digest, e)
    })
  })
}

pub fn val_to_str(val: &Value) -> String {
  with_externs(|e| {
    (e.val_to_str)(e.context, val).to_string().unwrap_or_else(|e| {
      format!("<failed to decode unicode for {:?}: {}>", val, e)
    })
  })
}

pub fn create_exception(msg: &str) -> Value {
  with_externs(|e|
    (e.create_exception)(e.context, msg.as_ptr(), msg.len() as u64)
  )
}

pub fn invoke_runnable(func: &Value, args: &[Value], cacheable: bool) -> Result<Value, Failure> {
  let result =
    with_externs(|e| {
      (e.invoke_runnable)(
        e.context,
        func,
        args.as_ptr(),
        args.len() as u64,
        cacheable
      )
    });
  if result.is_throw {
    let traceback = result.traceback.to_string().unwrap_or_else(|e| {
                      format!("<failed to decode unicode for {:?}: {}>", result.traceback, e)
                    });
    Err(Failure::Throw(result.value, traceback))
  } else {
    Ok(result.value)
  }
}

///
/// NB: Panics on failure. Only recommended for use with built-in functions, such as
/// those configured in types::Types.
///
pub fn invoke_unsafe(func: &Function, args: &Vec<Value>) -> Value {
  invoke_runnable(&val_for_id(func.0), args, false)
    .unwrap_or_else(|e| {
      panic!("Core function `{}` failed: {:?}", id_to_str(func.0), e);
    })
}

/////////////////////////////////////////////////////////////////////////////////////////
/// The remainder of this file deals with the static initialization of the Externs.
/////////////////////////////////////////////////////////////////////////////////////////

lazy_static! {
  static ref EXTERNS: RwLock<Option<Externs>> = RwLock::new(None);
}

///
/// Set the static Externs for this process. All other methods of this module will fail
/// until this has been called.
///
pub fn set_externs(externs: Externs) {
  let mut externs_ref = EXTERNS.write().unwrap();
  *externs_ref = Some(externs);
}

fn with_externs<F, T>(f: F) -> T where F: FnOnce(&Externs)->T {
  let externs_opt = EXTERNS.read().unwrap();
  let externs =
    externs_opt
      .as_ref()
      .unwrap_or_else(||
        panic!("externs used before static initialization.")
      );
  f(externs)
}

// An opaque pointer to a context used by the extern functions.
pub type ExternContext = raw::c_void;

pub struct Externs {
  context: *const ExternContext,
  log: LogExtern,
  key_for: KeyForExtern,
  val_for: ValForExtern,
  clone_val: CloneValExtern,
  drop_handles: DropHandlesExtern,
  satisfied_by: SatisfiedByExtern,
  satisfied_by_type: SatisfiedByTypeExtern,
  satisfied_by_type_cache: RwLock<HashMap<(TypeConstraint, TypeId), bool>>,
  store_list: StoreListExtern,
  store_bytes: StoreBytesExtern,
  project: ProjectExtern,
  project_ignoring_type: ProjectIgnoringTypeExtern,
  project_multi: ProjectMultiExtern,
  id_to_str: IdToStrExtern,
  val_to_str: ValToStrExtern,
  create_exception: CreateExceptionExtern,
  invoke_runnable: InvokeRunnable,
  // TODO: This type is also declared on `types::Types`.
  py_str_type: TypeId,
}

// The pointer to the context is safe for sharing between threads.
unsafe impl Sync for Externs {}
unsafe impl Send for Externs {}

impl Externs {
  pub fn new(
    ext_context: *const ExternContext,
    log: LogExtern,
    key_for: KeyForExtern,
    val_for: ValForExtern,
    clone_val: CloneValExtern,
    drop_handles: DropHandlesExtern,
    id_to_str: IdToStrExtern,
    val_to_str: ValToStrExtern,
    satisfied_by: SatisfiedByExtern,
    satisfied_by_type: SatisfiedByTypeExtern,
    store_list: StoreListExtern,
    store_bytes: StoreBytesExtern,
    project: ProjectExtern,
    project_ignoring_type: ProjectIgnoringTypeExtern,
    project_multi: ProjectMultiExtern,
    create_exception: CreateExceptionExtern,
    invoke_runnable: InvokeRunnable,
    py_str_type: TypeId,
  ) -> Externs {
    Externs {
      context: ext_context,
      log: log,
      key_for: key_for,
      val_for: val_for,
      clone_val: clone_val,
      drop_handles: drop_handles,
      satisfied_by: satisfied_by,
      satisfied_by_type: satisfied_by_type,
      satisfied_by_type_cache: RwLock::new(HashMap::new()),
      store_list: store_list,
      store_bytes: store_bytes,
      project: project,
      project_ignoring_type: project_ignoring_type,
      project_multi: project_multi,
      id_to_str: id_to_str,
      val_to_str: val_to_str,
      create_exception: create_exception,
      invoke_runnable: invoke_runnable,
      py_str_type: py_str_type
    }
  }
}

pub type LogExtern =
  extern "C" fn(*const ExternContext, u8, str_ptr: *const u8, str_len: u64);

pub type SatisfiedByExtern =
  extern "C" fn(*const ExternContext, *const TypeConstraint, *const Value) -> bool;

pub type SatisfiedByTypeExtern =
  extern "C" fn(*const ExternContext, *const TypeConstraint, *const TypeId) -> bool;

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

pub type StoreBytesExtern =
  extern "C" fn(*const ExternContext, *const u8, u64) -> Value;

pub type ProjectExtern =
  extern "C" fn(*const ExternContext, *const Value, field_name_ptr: *const u8, field_name_len: u64, *const TypeId) -> Value;

// Not all log levels are always in use.
#[allow(dead_code)]
#[repr(u8)]
pub enum LogLevel {
  Debug = 0,
  Info = 1,
  Warn = 2,
  Critical = 3,
}

#[repr(C)]
#[derive(Debug)]
pub struct RunnableComplete {
  value: Value,
  is_throw: bool,
  traceback: Buffer
}

// Points to an array containing a series of values allocated by Python.
#[repr(C)]
pub struct ValueBuffer {
  values_ptr: *mut Value,
  values_len: u64,
  // A Value handle to hold the underlying buffer alive.
  handle_: Value,
}

impl ValueBuffer {
  pub fn to_vec(&self) -> Vec<Value> {
    with_vec(self.values_ptr, self.values_len as usize, |value_vec| {
      unsafe {
        value_vec.iter().map(|v| v.clone_without_handle()).collect()
      }
    })
  }
}

// Points to an array of TypeIds.
#[repr(C)]
#[derive(Debug)]
pub struct TypeIdBuffer {
  ids_ptr: *mut TypeId,
  ids_len: u64,
  // handle to hold the underlying array alive
  handle_: Value
}

impl TypeIdBuffer {
  pub fn to_vec(&self) -> Vec<TypeId> {
    with_vec(self.ids_ptr, self.ids_len as usize, |vec| {
      vec.clone()
    })
  }
}

pub type ProjectIgnoringTypeExtern =
  extern "C" fn(*const ExternContext, *const Value, field_name_ptr: *const u8, field_name_len: u64) -> Value;

pub type ProjectMultiExtern =
  extern "C" fn(*const ExternContext, *const Value, field_name_ptr: *const u8, field_name_len: u64) -> ValueBuffer;

#[repr(C)]
#[derive(Debug)]
pub struct Buffer {
  bytes_ptr: *mut u8,
  bytes_len: u64,
  // A Value handle to hold the underlying array alive.
  handle_: Value,
}

impl Buffer {
  pub fn to_bytes(&self) -> Vec<u8> {
    with_vec(self.bytes_ptr, self.bytes_len as usize, |vec| {
      vec.clone()
    })
  }

  pub fn to_os_string(&self) -> OsString {
    OsString::from_vec(self.to_bytes())
  }

  pub fn to_string(&self) -> Result<String, FromUtf8Error> {
    String::from_utf8(self.to_bytes())
  }
}

// Points to an array of (byte) Buffers.
#[repr(C)]
pub struct BufferBuffer {
  bufs_ptr: *mut Buffer,
  bufs_len: u64,
  // handle to hold the underlying array alive
  handle_: Value,
}

impl BufferBuffer {
  pub fn to_bytes_vecs(&self) -> Vec<Vec<u8>> {
    with_vec(self.bufs_ptr, self.bufs_len as usize, |vec| {
      vec.iter().map(|b| b.to_bytes()).collect()
    })
  }

  pub fn to_os_strings(&self) -> Vec<OsString> {
    self.to_bytes_vecs().into_iter().map(|v| OsString::from_vec(v)).collect()
  }

  pub fn to_strings(&self) -> Result<Vec<String>,FromUtf8Error> {
    self.to_bytes_vecs().into_iter()
      .map(|v| String::from_utf8(v))
      .collect()
  }
}

pub type IdToStrExtern =
  extern "C" fn(*const ExternContext, Id) -> Buffer;

pub type ValToStrExtern =
  extern "C" fn(*const ExternContext, *const Value) -> Buffer;

pub type CreateExceptionExtern =
  extern "C" fn(*const ExternContext, str_ptr: *const u8, str_len: u64) -> Value;

pub type InvokeRunnable =
  extern "C" fn(*const ExternContext, *const Value, *const Value, u64, bool) -> RunnableComplete;

pub fn with_vec<F, C, T>(c_ptr: *mut C, c_len: usize, f: F) -> T
    where F: FnOnce(&Vec<C>)->T {
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  mem::forget(cs);
  output
}
