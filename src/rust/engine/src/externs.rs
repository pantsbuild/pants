// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::ffi::OsString;
use std::hash;
use std::mem;
use std::os::raw;
use std::os::unix::ffi::OsStringExt;
use std::string::FromUtf8Error;
use std::sync::RwLock;

use core::{Failure, FNV, Function, Id, Key, TypeConstraint, TypeId, Value};
use handles::Handle;


pub fn log(level: LogLevel, msg: &str) {
  with_externs(|e| {
    (e.log)(e.context, level as u8, msg.as_ptr(), msg.len() as u64)
  })
}

pub fn eval(python: &str) -> Result<Value, Failure> {
  with_externs(|e| {
    (e.eval)(e.context, python.as_ptr(), python.len() as u64)
  }).into()
}

fn identify(val: &Value) -> Ident {
  with_externs(|e| (e.identify)(e.context, val))
}

pub fn equals(val1: &Value, val2: &Value) -> bool {
  with_externs(|e| (e.equals)(e.context, val1, val2))
}

pub fn key_for(val: &Value) -> Key {
  let mut interns = INTERNS.write().unwrap();
  interns.insert(val)
}

pub fn val_for(key: &Key) -> Value {
  let interns = INTERNS.read().unwrap();
  interns.get(key).clone()
}

pub fn clone_val(val: &Value) -> Value {
  with_externs(|e| (e.clone_val)(e.context, val))
}

pub fn drop_handles(handles: Vec<Handle>) {
  with_externs(|e| {
    (e.drop_handles)(e.context, handles.as_ptr(), handles.len() as u64)
  })
}

pub fn satisfied_by(constraint: &TypeConstraint, obj: &Value) -> bool {
  let interns = INTERNS.read().unwrap();
  with_externs(|e| {
    (e.satisfied_by)(e.context, interns.get(&constraint.0), obj)
  })
}

pub fn satisfied_by_type(constraint: &TypeConstraint, cls: &TypeId) -> bool {
  let interns = INTERNS.read().unwrap();
  with_externs(|e| {
    (e.satisfied_by_type)(e.context, interns.get(&constraint.0), cls)
  })
}

pub fn store_list(values: Vec<&Value>, merge: bool) -> Value {
  with_externs(|e| {
    let values_clone: Vec<*const Value> = values.into_iter().map(|v| v as *const Value).collect();
    (e.store_list)(
      e.context,
      values_clone.as_ptr(),
      values_clone.len() as u64,
      merge,
    )
  })
}

pub fn store_bytes(bytes: &[u8]) -> Value {
  with_externs(|e| {
    (e.store_bytes)(e.context, bytes.as_ptr(), bytes.len() as u64)
  })
}

pub fn store_i32(val: i32) -> Value {
  with_externs(|e| (e.store_i32)(e.context, val))
}

pub fn project(value: &Value, field: &str, type_id: &TypeId) -> Value {
  with_externs(|e| {
    (e.project)(
      e.context,
      value,
      field.as_ptr(),
      field.len() as u64,
      type_id,
    )
  })
}

pub fn project_ignoring_type(value: &Value, field: &str) -> Value {
  with_externs(|e| {
    (e.project_ignoring_type)(e.context, value, field.as_ptr(), field.len() as u64)
  })
}

pub fn project_multi(value: &Value, field: &str) -> Vec<Value> {
  with_externs(|e| {
    (e.project_multi)(e.context, value, field.as_ptr(), field.len() as u64).to_vec()
  })
}

pub fn project_multi_strs(item: &Value, field: &str) -> Vec<String> {
  project_multi(item, field)
    .iter()
    .map(|v| val_to_str(v))
    .collect()
}

pub fn project_str(value: &Value, field: &str) -> String {
  let name_val = with_externs(|e| {
    (e.project)(
      e.context,
      value,
      field.as_ptr(),
      field.len() as u64,
      &e.py_str_type,
    )
  });
  val_to_str(&name_val)
}

pub fn key_to_str(key: &Key) -> String {
  val_to_str(&val_for(key))
}

pub fn id_to_str(digest: Id) -> String {
  with_externs(|e| {
    (e.id_to_str)(e.context, digest)
      .to_string()
      .unwrap_or_else(|e| {
        format!("<failed to decode unicode for {:?}: {}>", digest, e)
      })
  })
}

pub fn val_to_str(val: &Value) -> String {
  with_externs(|e| {
    (e.val_to_str)(e.context, val).to_string().unwrap_or_else(
      |e| {
        format!("<failed to decode unicode for {:?}: {}>", val, e)
      },
    )
  })
}

pub fn create_exception(msg: &str) -> Value {
  with_externs(|e| {
    (e.create_exception)(e.context, msg.as_ptr(), msg.len() as u64)
  })
}

pub fn call_method(value: &Value, method: &str, args: &[Value]) -> Result<Value, Failure> {
  call(&project_ignoring_type(&value, method), args)
}

pub fn call(func: &Value, args: &[Value]) -> Result<Value, Failure> {
  with_externs(|e| {
    (e.call)(e.context, func, args.as_ptr(), args.len() as u64)
  }).into()
}

///
/// NB: Panics on failure. Only recommended for use with built-in functions, such as
/// those configured in types::Types.
///
pub fn unsafe_call(func: &Function, args: &Vec<Value>) -> Value {
  let interns = INTERNS.read().unwrap();
  let func_val = interns.get(&func.0);
  call(func_val, args).unwrap_or_else(|e| {
    panic!("Core function `{}` failed: {:?}", val_to_str(func_val), e);
  })
}

/////////////////////////////////////////////////////////////////////////////////////////
/// The remainder of this file deals with the static initialization of the Externs.
/////////////////////////////////////////////////////////////////////////////////////////

lazy_static! {
  static ref EXTERNS: RwLock<Option<Externs>> = RwLock::new(None);
  static ref INTERNS: RwLock<Interns> = RwLock::new(Default::default());
}

///
/// Set the static Externs for this process. All other methods of this module will fail
/// until this has been called.
///
pub fn set_externs(externs: Externs) {
  let mut externs_ref = EXTERNS.write().unwrap();
  *externs_ref = Some(externs);
}

fn with_externs<F, T>(f: F) -> T
where
  F: FnOnce(&Externs) -> T,
{
  let externs_opt = EXTERNS.read().unwrap();
  let externs = externs_opt.as_ref().unwrap_or_else(|| {
    panic!("externs used before static initialization.")
  });
  f(externs)
}

// An opaque pointer to a context used by the extern functions.
pub type ExternContext = raw::c_void;

pub struct Externs {
  context: *const ExternContext,
  log: LogExtern,
  call: CallExtern,
  eval: EvalExtern,
  identify: IdentifyExtern,
  equals: EqualsExtern,
  clone_val: CloneValExtern,
  drop_handles: DropHandlesExtern,
  satisfied_by: SatisfiedByExtern,
  satisfied_by_type: SatisfiedByTypeExtern,
  store_list: StoreListExtern,
  store_bytes: StoreBytesExtern,
  store_i32: StoreI32Extern,
  project: ProjectExtern,
  project_ignoring_type: ProjectIgnoringTypeExtern,
  project_multi: ProjectMultiExtern,
  id_to_str: IdToStrExtern,
  val_to_str: ValToStrExtern,
  create_exception: CreateExceptionExtern,
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
    call: CallExtern,
    eval: EvalExtern,
    identify: IdentifyExtern,
    equals: EqualsExtern,
    clone_val: CloneValExtern,
    drop_handles: DropHandlesExtern,
    id_to_str: IdToStrExtern,
    val_to_str: ValToStrExtern,
    satisfied_by: SatisfiedByExtern,
    satisfied_by_type: SatisfiedByTypeExtern,
    store_list: StoreListExtern,
    store_bytes: StoreBytesExtern,
    store_i32: StoreI32Extern,
    project: ProjectExtern,
    project_ignoring_type: ProjectIgnoringTypeExtern,
    project_multi: ProjectMultiExtern,
    create_exception: CreateExceptionExtern,
    py_str_type: TypeId,
  ) -> Externs {
    Externs {
      context: ext_context,
      log: log,
      call: call,
      eval: eval,
      identify: identify,
      equals: equals,
      clone_val: clone_val,
      drop_handles: drop_handles,
      satisfied_by: satisfied_by,
      satisfied_by_type: satisfied_by_type,
      store_list: store_list,
      store_bytes: store_bytes,
      store_i32: store_i32,
      project: project,
      project_ignoring_type: project_ignoring_type,
      project_multi: project_multi,
      id_to_str: id_to_str,
      val_to_str: val_to_str,
      create_exception: create_exception,
      py_str_type: py_str_type,
    }
  }
}

struct InternKey(i64, Value);

impl Eq for InternKey {}

impl PartialEq for InternKey {
  fn eq(&self, other: &InternKey) -> bool {
    equals(&self.1, &other.1)
  }
}

impl hash::Hash for InternKey {
  fn hash<H: hash::Hasher>(&self, state: &mut H) {
    self.0.hash(state);
  }
}

#[derive(Default)]
struct Interns {
  forward: HashMap<InternKey, Key, FNV>,
  reverse: HashMap<Id, Value, FNV>,
  id_generator: u64,
}

impl Interns {
  fn insert(&mut self, v: &Value) -> Key {
    let ident = identify(v);
    let type_id = ident.type_id;
    let mut maybe_id = self.id_generator;
    let key = self
      .forward
      .entry(InternKey(ident.hash, ident.value))
      .or_insert_with(|| {
        maybe_id += 1;
        Key::new(maybe_id, type_id)
      })
      .clone();
    if maybe_id != self.id_generator {
      self.id_generator = maybe_id;
      self.reverse.insert(maybe_id, v.clone());
    }
    key
  }

  fn get(&self, k: &Key) -> &Value {
    self.reverse.get(&k.id()).unwrap_or_else(|| {
      panic!("Previously memoized object disappeared for {:?}", k)
    })
  }
}

pub type LogExtern = extern "C" fn(*const ExternContext, u8, str_ptr: *const u8, str_len: u64);

// TODO: Type alias used to avoid rustfmt breaking itself by rendering a 101 character line.
pub type SatisifedBool = bool;
pub type SatisfiedByExtern = extern "C" fn(*const ExternContext, *const Value, *const Value)
                                           -> SatisifedBool;

pub type SatisfiedByTypeExtern = extern "C" fn(*const ExternContext, *const Value, *const TypeId)
                                               -> bool;

pub type IdentifyExtern = extern "C" fn(*const ExternContext, *const Value) -> Ident;

pub type EqualsExtern = extern "C" fn(*const ExternContext, *const Value, *const Value) -> bool;

pub type CloneValExtern = extern "C" fn(*const ExternContext, *const Value) -> Value;

pub type DropHandlesExtern = extern "C" fn(*const ExternContext, *const Handle, u64);

pub type StoreListExtern = extern "C" fn(*const ExternContext, *const *const Value, u64, bool)
                                         -> Value;

pub type StoreBytesExtern = extern "C" fn(*const ExternContext, *const u8, u64) -> Value;

pub type StoreI32Extern = extern "C" fn(*const ExternContext, i32) -> Value;

pub type ProjectExtern = extern "C" fn(*const ExternContext,
                                       *const Value,
                                       field_name_ptr: *const u8,
                                       field_name_len: u64,
                                       *const TypeId)
                                       -> Value;

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
pub struct PyResult {
  is_throw: bool,
  value: Value,
}

impl From<PyResult> for Result<Value, Failure> {
  fn from(result: PyResult) -> Self {
    if result.is_throw {
      let traceback = project_str(&result.value, "_formatted_exc");
      Err(Failure::Throw(result.value, traceback))
    } else {
      Ok(result.value)
    }
  }
}

impl From<Result<(), String>> for PyResult {
  fn from(res: Result<(), String>) -> Self {
    match res {
      Ok(()) => PyResult { is_throw: false, value: eval("None").unwrap() },
      Err(msg) => PyResult {
        is_throw: true,
        value: create_exception(&msg),
      },
    }
  }
}

// The result of an `identify` call, including the __hash__ of a Value and its TypeId.
#[repr(C)]
pub struct Ident {
  hash: i64,
  value: Value,
  type_id: TypeId,
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
    with_vec(
      self.values_ptr,
      self.values_len as usize,
      |value_vec| unsafe { value_vec.iter().map(|v| v.clone_without_handle()).collect() },
    )
  }
}

// Points to an array of TypeIds.
#[repr(C)]
#[derive(Debug)]
pub struct TypeIdBuffer {
  ids_ptr: *mut TypeId,
  ids_len: u64,
  // handle to hold the underlying array alive
  handle_: Value,
}

impl TypeIdBuffer {
  pub fn to_vec(&self) -> Vec<TypeId> {
    with_vec(self.ids_ptr, self.ids_len as usize, |vec| vec.clone())
  }
}

pub type ProjectIgnoringTypeExtern = extern "C" fn(*const ExternContext,
                                                   *const Value,
                                                   field_name_ptr: *const u8,
                                                   field_name_len: u64)
                                                   -> Value;

pub type ProjectMultiExtern = extern "C" fn(*const ExternContext,
                                            *const Value,
                                            field_name_ptr: *const u8,
                                            field_name_len: u64)
                                            -> ValueBuffer;

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
    with_vec(self.bytes_ptr, self.bytes_len as usize, |vec| vec.clone())
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
    self
      .to_bytes_vecs()
      .into_iter()
      .map(|v| OsString::from_vec(v))
      .collect()
  }

  pub fn to_strings(&self) -> Result<Vec<String>, FromUtf8Error> {
    self
      .to_bytes_vecs()
      .into_iter()
      .map(|v| String::from_utf8(v))
      .collect()
  }
}

pub type IdToStrExtern = extern "C" fn(*const ExternContext, Id) -> Buffer;

pub type ValToStrExtern = extern "C" fn(*const ExternContext, *const Value) -> Buffer;

pub type CreateExceptionExtern = extern "C" fn(*const ExternContext,
                                               str_ptr: *const u8,
                                               str_len: u64)
                                               -> Value;

pub type CallExtern = extern "C" fn(*const ExternContext, *const Value, *const Value, u64)
                                    -> PyResult;

pub type EvalExtern = extern "C" fn(*const ExternContext, python_ptr: *const u8, python_len: u64)
                                    -> PyResult;

pub fn with_vec<F, C, T>(c_ptr: *mut C, c_len: usize, f: F) -> T
where
  F: FnOnce(&Vec<C>) -> T,
{
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  mem::forget(cs);
  output
}
