// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ffi::OsStr;
use std::ffi::OsString;
use std::fmt;
use std::mem;
use std::os::raw;
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::string::FromUtf8Error;

use crate::core::{Failure, Function, Key, TypeId, Value};
use crate::handles::{DroppingHandle, Handle};
use crate::interning::Interns;
use lazy_static::lazy_static;
use parking_lot::RwLock;

/// Return the Python value None.
pub fn none() -> Handle {
  with_externs(|e| (e.clone_val)(e.context, &e.none))
}

pub fn get_type_for(val: &Value) -> TypeId {
  with_externs(|e| (e.get_type_for)(e.context, val as &Handle))
}

pub fn identify(val: &Value) -> Ident {
  with_externs(|e| (e.identify)(e.context, val as &Handle))
}

pub fn equals(h1: &Handle, h2: &Handle) -> bool {
  with_externs(|e| (e.equals)(e.context, h1, h2))
}

pub fn key_for(val: Value) -> Key {
  let mut interns = INTERNS.write();
  interns.insert(val)
}

pub fn val_for(key: &Key) -> Value {
  let interns = INTERNS.read();
  interns.get(key).clone()
}

pub fn clone_val(handle: &Handle) -> Handle {
  with_externs(|e| (e.clone_val)(e.context, handle))
}

pub fn drop_handles(handles: &[DroppingHandle]) {
  with_externs(|e| (e.drop_handles)(e.context, handles.as_ptr(), handles.len() as u64))
}

pub fn store_tuple(values: &[Value]) -> Value {
  let handles: Vec<_> = values
    .iter()
    .map(|v| v as &Handle as *const Handle)
    .collect();
  with_externs(|e| (e.store_tuple)(e.context, handles.as_ptr(), handles.len() as u64).into())
}

#[allow(dead_code)]
pub fn store_set<I: Iterator<Item = Value>>(values: I) -> Value {
  let handles: Vec<_> = values.map(|v| &v as &Handle as *const Handle).collect();
  with_externs(|e| (e.store_set)(e.context, handles.as_ptr(), handles.len() as u64).into())
}

///
/// Store a dict of values, which are stored in a slice alternating interleaved keys and values,
/// i.e. stored (key0, value0, key1, value1, ...)
///
/// The underlying slice _must_ contain an even number of elements.
///
pub fn store_dict(keys_and_values_interleaved: &[(Value)]) -> Value {
  if keys_and_values_interleaved.len() % 2 != 0 {
    panic!("store_dict requires an even number of elements");
  }
  let handles: Vec<_> = keys_and_values_interleaved
    .iter()
    .map(|v| v as &Handle as *const Handle)
    .collect();
  with_externs(|e| (e.store_dict)(e.context, handles.as_ptr(), handles.len() as u64).into())
}

///
/// Store an opqaue buffer of bytes to pass to Python. This will end up as a Python `bytes`.
///
pub fn store_bytes(bytes: &[u8]) -> Value {
  with_externs(|e| (e.store_bytes)(e.context, bytes.as_ptr(), bytes.len() as u64).into())
}

///
/// Store an buffer of utf8 bytes to pass to Python. This will end up as a Python `unicode`.
///
pub fn store_utf8(utf8: &str) -> Value {
  with_externs(|e| (e.store_utf8)(e.context, utf8.as_ptr(), utf8.len() as u64).into())
}

///
/// Store a buffer of utf8 bytes to pass to Python. This will end up as a Python `unicode`.
///
#[cfg(unix)]
pub fn store_utf8_osstr(utf8: &OsStr) -> Value {
  let bytes = utf8.as_bytes();
  with_externs(|e| (e.store_utf8)(e.context, bytes.as_ptr(), bytes.len() as u64).into())
}

pub fn store_i64(val: i64) -> Value {
  with_externs(|e| (e.store_i64)(e.context, val).into())
}

#[allow(dead_code)]
pub fn store_f64(val: f64) -> Value {
  with_externs(|e| (e.store_f64)(e.context, val).into())
}

#[allow(dead_code)]
pub fn store_bool(val: bool) -> Value {
  with_externs(|e| (e.store_bool)(e.context, val).into())
}

///
/// Pulls out the value specified by the field name from a given Value
///
pub fn project_ignoring_type(value: &Value, field: &str) -> Value {
  with_externs(|e| {
    (e.project_ignoring_type)(
      e.context,
      value as &Handle,
      field.as_ptr(),
      field.len() as u64,
    )
    .into()
  })
}

pub fn project_multi(value: &Value, field: &str) -> Vec<Value> {
  with_externs(|e| {
    (e.project_multi)(
      e.context,
      value as &Handle,
      field.as_ptr(),
      field.len() as u64,
    )
    .to_vec()
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
    (e.project_ignoring_type)(
      e.context,
      value as &Handle,
      field.as_ptr(),
      field.len() as u64,
    )
    .into()
  });
  val_to_str(&name_val)
}

pub fn key_to_str(key: &Key) -> String {
  val_to_str(&val_for(key))
}

pub fn type_to_str(type_id: TypeId) -> String {
  with_externs(|e| {
    (e.type_to_str)(e.context, type_id)
      .to_string()
      .unwrap_or_else(|e| format!("<failed to decode unicode for {:?}: {}>", type_id, e))
  })
}

pub fn val_to_str(val: &Value) -> String {
  with_externs(|e| {
    (e.val_to_str)(e.context, val as &Handle)
      .to_string()
      .unwrap_or_else(|e| format!("<failed to decode unicode for {:?}: {}>", val, e))
  })
}

pub fn create_exception(msg: &str) -> Value {
  with_externs(|e| (e.create_exception)(e.context, msg.as_ptr(), msg.len() as u64).into())
}

// TODO: This method is currently unused, but kept as an example of how to call methods on objects.
#[allow(dead_code)]
pub fn call_method(value: &Value, method: &str, args: &[Value]) -> Result<Value, Failure> {
  call(&project_ignoring_type(&value, method), args)
}

pub fn call(func: &Value, args: &[Value]) -> Result<Value, Failure> {
  let arg_handles: Vec<_> = args.iter().map(|v| v as &Handle as *const Handle).collect();
  with_externs(|e| {
    (e.call)(
      e.context,
      func as &Handle,
      arg_handles.as_ptr(),
      args.len() as u64,
    )
  })
  .into()
}

pub fn generator_send(generator: &Value, arg: &Value) -> Result<GeneratorResponse, Failure> {
  let response =
    with_externs(|e| (e.generator_send)(e.context, generator as &Handle, arg as &Handle));
  match response {
    PyGeneratorResponse::Broke(h) => Ok(GeneratorResponse::Break(Value::new(h))),
    PyGeneratorResponse::Throw(h) => Err(PyResult::failure_from(Value::new(h))),
    PyGeneratorResponse::Get(product, handle, ident) => {
      let mut interns = INTERNS.write();
      let g = Get {
        product,
        subject: interns.insert_with(Value::new(handle), ident),
      };
      Ok(GeneratorResponse::Get(g))
    }
    PyGeneratorResponse::GetMulti(products, handles, identities) => {
      let mut interns = INTERNS.write();
      let products = products.to_vec();
      let identities = identities.to_vec();
      let values = handles.to_vec();
      assert_eq!(products.len(), values.len());
      let gets: Vec<Get> = products
        .into_iter()
        .zip(values.into_iter())
        .zip(identities.into_iter())
        .map(|((p, v), i)| Get {
          product: p,
          subject: interns.insert_with(v, i),
        })
        .collect();
      Ok(GeneratorResponse::GetMulti(gets))
    }
  }
}

///
/// Calls the given function with exclusive access to all locks managed by this module.
/// Used to ensure that the main thread forks with all locks acquired.
///
pub fn exclusive_call(func: &Key) -> Result<Value, Failure> {
  // NB: Acquiring the interns exclusively as well.
  let interns = INTERNS.write();
  let func_val = interns.get(func);
  with_externs_exclusive(|e| (e.call)(e.context, func_val as &Handle, &[].as_ptr(), 0)).into()
}

///
/// NB: Panics on failure. Only recommended for use with built-in functions, such as
/// those configured in types::Types.
///
pub fn unsafe_call(func: &Function, args: &[Value]) -> Value {
  let interns = INTERNS.read();
  let func_val = interns.get(&func.0);
  call(func_val, args).unwrap_or_else(|e| {
    panic!("Core function `{}` failed: {:?}", val_to_str(func_val), e);
  })
}

/////////////////////////////////////////////////////////////////////////////////////////
/// The remainder of this file deals with the static initialization of the Externs.
/////////////////////////////////////////////////////////////////////////////////////////

lazy_static! {
  // NB: Unfortunately, it's not currently possible to merge these locks, because mutating
  // the `Interns` requires calls to extern functions, which would be re-entrant.
  static ref EXTERNS: RwLock<Option<Externs>> = RwLock::new(None);
  static ref INTERNS: RwLock<Interns> = RwLock::new(Interns::new());
}

///
/// Set the static Externs for this process. All other methods of this module will fail
/// until this has been called.
///
pub fn set_externs(externs: Externs) {
  let mut externs_ref = EXTERNS.write();
  *externs_ref = Some(externs);
}

fn with_externs<F, T>(f: F) -> T
where
  F: FnOnce(&Externs) -> T,
{
  let externs_opt = EXTERNS.read();
  let externs = externs_opt
    .as_ref()
    .unwrap_or_else(|| panic!("externs used before static initialization."));
  f(externs)
}

fn with_externs_exclusive<F, T>(f: F) -> T
where
  F: FnOnce(&Externs) -> T,
{
  let externs_opt = EXTERNS.write();
  let externs = externs_opt
    .as_ref()
    .unwrap_or_else(|| panic!("externs used before static initialization."));
  f(externs)
}

// An opaque pointer to a context used by the extern functions.
pub type ExternContext = raw::c_void;

pub struct Externs {
  pub context: *const ExternContext,
  pub log_level: u8,
  pub none: Handle,
  pub call: CallExtern,
  pub generator_send: GeneratorSendExtern,
  pub get_type_for: GetTypeForExtern,
  pub identify: IdentifyExtern,
  pub equals: EqualsExtern,
  pub clone_val: CloneValExtern,
  pub drop_handles: DropHandlesExtern,
  pub store_tuple: StoreTupleExtern,
  pub store_set: StoreTupleExtern,
  pub store_dict: StoreTupleExtern,
  pub store_bytes: StoreBytesExtern,
  pub store_utf8: StoreUtf8Extern,
  pub store_i64: StoreI64Extern,
  pub store_f64: StoreF64Extern,
  pub store_bool: StoreBoolExtern,
  pub project_ignoring_type: ProjectIgnoringTypeExtern,
  pub project_multi: ProjectMultiExtern,
  pub type_to_str: TypeToStrExtern,
  pub val_to_str: ValToStrExtern,
  pub create_exception: CreateExceptionExtern,
}

// The pointer to the context is safe for sharing between threads.
unsafe impl Sync for Externs {}
unsafe impl Send for Externs {}

pub type GetTypeForExtern = extern "C" fn(*const ExternContext, *const Handle) -> TypeId;

pub type IdentifyExtern = extern "C" fn(*const ExternContext, *const Handle) -> Ident;

pub type EqualsExtern = extern "C" fn(*const ExternContext, *const Handle, *const Handle) -> bool;

pub type CloneValExtern = extern "C" fn(*const ExternContext, *const Handle) -> Handle;

pub type DropHandlesExtern = extern "C" fn(*const ExternContext, *const DroppingHandle, u64);

pub type StoreTupleExtern =
  extern "C" fn(*const ExternContext, *const *const Handle, u64) -> Handle;

pub type StoreBytesExtern = extern "C" fn(*const ExternContext, *const u8, u64) -> Handle;

pub type StoreUtf8Extern = extern "C" fn(*const ExternContext, *const u8, u64) -> Handle;

pub type StoreI64Extern = extern "C" fn(*const ExternContext, i64) -> Handle;

pub type StoreF64Extern = extern "C" fn(*const ExternContext, f64) -> Handle;

pub type StoreBoolExtern = extern "C" fn(*const ExternContext, bool) -> Handle;

///
/// NB: When a PyResult is handed from Python to Rust, the Rust side destroys the handle. But when
/// it is passed from Rust to Python, Python must destroy the handle.
///
#[repr(C)]
pub struct PyResult {
  is_throw: bool,
  handle: Handle,
}

impl PyResult {
  fn failure_from(v: Value) -> Failure {
    let traceback = project_str(&v, "_formatted_exc");
    Failure::Throw(v, traceback)
  }
}

impl From<Result<Value, Failure>> for PyResult {
  fn from(result: Result<Value, Failure>) -> Self {
    match result {
      Ok(val) => PyResult {
        is_throw: false,
        handle: val.into(),
      },
      Err(f) => {
        let val = match f {
          f @ Failure::Invalidated => create_exception(&format!("{}", f)),
          Failure::Throw(exc, _) => exc,
        };
        PyResult {
          is_throw: true,
          handle: val.into(),
        }
      }
    }
  }
}

impl From<PyResult> for Result<Value, Failure> {
  fn from(result: PyResult) -> Self {
    let value = result.handle.into();
    if result.is_throw {
      Err(PyResult::failure_from(value))
    } else {
      Ok(value)
    }
  }
}

impl From<Result<Value, String>> for PyResult {
  fn from(res: Result<Value, String>) -> Self {
    match res {
      Ok(v) => PyResult {
        is_throw: false,
        handle: v.into(),
      },
      Err(msg) => PyResult {
        is_throw: true,
        handle: create_exception(&msg).into(),
      },
    }
  }
}

impl From<Result<(), String>> for PyResult {
  fn from(res: Result<(), String>) -> Self {
    PyResult::from(res.map(|()| Value::from(none())))
  }
}

///
/// The response from a call to extern_generator_send. Gets include Idents for their Handles
/// in order to avoid roundtripping to intern them, and to eagerly trigger errors for unhashable
/// types on the python side where possible.
///
#[repr(C)]
pub enum PyGeneratorResponse {
  Get(TypeId, Handle, Ident),
  GetMulti(TypeIdBuffer, HandleBuffer, IdentBuffer),
  // NB: Broke not Break because C keyword.
  Broke(Handle),
  Throw(Handle),
}

#[derive(Debug)]
pub struct Get {
  pub product: TypeId,
  pub subject: Key,
}

impl fmt::Display for Get {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    write!(
      f,
      "Get({}, {})",
      type_to_str(self.product),
      key_to_str(&self.subject)
    )
  }
}

pub enum GeneratorResponse {
  Break(Value),
  Get(Get),
  GetMulti(Vec<Get>),
}

///
/// The result of an `identify` call, including the __hash__ of a Handle and a TypeId representing
/// the object's type.
///
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Ident {
  pub hash: i64,
  pub type_id: TypeId,
}

pub trait RawBuffer<Raw, Output> {
  fn ptr(&self) -> *mut Raw;
  fn len(&self) -> u64;

  ///
  /// A buffer-specific shallow clone operation (possibly just implemented via clone).
  ///
  fn lift(t: &Raw) -> Output;

  ///
  /// Returns a Vec copy of the buffer contents.
  ///
  fn to_vec(&self) -> Vec<Output> {
    with_vec(self.ptr(), self.len() as usize, |vec| {
      vec.iter().map(Self::lift).collect()
    })
  }

  ///
  /// Asserts that the buffer contains one item, and returns a copy of it.
  ///
  fn unwrap_one(&self) -> Output {
    assert!(
      self.len() == 1,
      "Expected exactly 1 item in Buffer, but had: {}",
      self.len()
    );
    with_vec(self.ptr(), self.len() as usize, |vec| Self::lift(&vec[0]))
  }
}

///
/// Points to an array containing a series of values allocated by Python.
///
/// TODO: An interesting optimization might be possible where we avoid actually
/// allocating the values array for values_len == 1, and instead store the Handle in
/// the `handle_` field.
///
#[repr(C)]
pub struct HandleBuffer {
  handles_ptr: *mut Handle,
  handles_len: u64,
  // A Handle to hold the underlying buffer alive.
  handle_: Handle,
}

impl RawBuffer<Handle, Value> for HandleBuffer {
  fn ptr(&self) -> *mut Handle {
    self.handles_ptr
  }

  fn len(&self) -> u64 {
    self.handles_len
  }

  fn lift(t: &Handle) -> Value {
    Value::new(unsafe { t.clone_shallow() })
  }
}

#[repr(C)]
pub struct IdentBuffer {
  idents_ptr: *mut Ident,
  idents_len: u64,
  // A Handle to hold the underlying array alive.
  handle_: Handle,
}

impl RawBuffer<Ident, Ident> for IdentBuffer {
  fn ptr(&self) -> *mut Ident {
    self.idents_ptr
  }

  fn len(&self) -> u64 {
    self.idents_len
  }

  fn lift(t: &Ident) -> Ident {
    *t
  }
}

#[repr(C)]
pub struct TypeIdBuffer {
  ids_ptr: *mut TypeId,
  ids_len: u64,
  // A Handle to hold the underlying array alive.
  handle_: Handle,
}

impl RawBuffer<TypeId, TypeId> for TypeIdBuffer {
  fn ptr(&self) -> *mut TypeId {
    self.ids_ptr
  }

  fn len(&self) -> u64 {
    self.ids_len
  }

  fn lift(t: &TypeId) -> TypeId {
    *t
  }
}

pub type ProjectIgnoringTypeExtern = extern "C" fn(
  *const ExternContext,
  *const Handle,
  field_name_ptr: *const u8,
  field_name_len: u64,
) -> Handle;

pub type ProjectMultiExtern = extern "C" fn(
  *const ExternContext,
  *const Handle,
  field_name_ptr: *const u8,
  field_name_len: u64,
) -> HandleBuffer;

#[repr(C)]
pub struct Buffer {
  bytes_ptr: *mut u8,
  bytes_len: u64,
  // A Handle to hold the underlying array alive.
  handle_: Handle,
}

impl Buffer {
  pub fn to_bytes(&self) -> Vec<u8> {
    with_vec(self.bytes_ptr, self.bytes_len as usize, Vec::clone)
  }

  pub fn to_os_string(&self) -> OsString {
    OsString::from_vec(self.to_bytes())
  }

  pub fn to_string(&self) -> Result<String, FromUtf8Error> {
    String::from_utf8(self.to_bytes())
  }
}

///
/// Points to an array of (byte) Buffers.
///
/// TODO: Because this is only ever passed from Python to Rust, it could just use
/// `project_multi_strs`.
///
#[repr(C)]
pub struct BufferBuffer {
  bufs_ptr: *mut Buffer,
  bufs_len: u64,
  // A Handle to hold the underlying array alive.
  handle_: Handle,
}

impl BufferBuffer {
  pub fn to_bytes_vecs(&self) -> Vec<Vec<u8>> {
    with_vec(self.bufs_ptr, self.bufs_len as usize, |vec| {
      vec.iter().map(Buffer::to_bytes).collect()
    })
  }

  pub fn to_os_strings(&self) -> Vec<OsString> {
    self
      .to_bytes_vecs()
      .into_iter()
      .map(OsString::from_vec)
      .collect()
  }

  pub fn to_strings(&self) -> Result<Vec<String>, FromUtf8Error> {
    self
      .to_bytes_vecs()
      .into_iter()
      .map(String::from_utf8)
      .collect()
  }
}

pub type TypeToStrExtern = extern "C" fn(*const ExternContext, TypeId) -> Buffer;

pub type ValToStrExtern = extern "C" fn(*const ExternContext, *const Handle) -> Buffer;

pub type CreateExceptionExtern =
  extern "C" fn(*const ExternContext, str_ptr: *const u8, str_len: u64) -> Handle;

pub type CallExtern =
  extern "C" fn(*const ExternContext, *const Handle, *const *const Handle, u64) -> PyResult;

pub type GeneratorSendExtern =
  extern "C" fn(*const ExternContext, *const Handle, *const Handle) -> PyGeneratorResponse;

pub fn with_vec<F, C, T>(c_ptr: *mut C, c_len: usize, f: F) -> T
where
  F: FnOnce(&Vec<C>) -> T,
{
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  mem::forget(cs);
  output
}
