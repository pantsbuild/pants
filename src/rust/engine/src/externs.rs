// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ffi::OsString;
use std::mem;
use std::os::raw;
use std::os::unix::ffi::OsStringExt;
use std::string::FromUtf8Error;
use std::sync::RwLock;

use core::{Failure, Function, Key, TypeConstraint, TypeId, Value};
use enum_primitive::FromPrimitive;
use handles::Handle;
use interning::Interns;
use log;

pub fn eval(python: &str) -> Result<Value, Failure> {
  with_externs(|e| (e.eval)(e.context, python.as_ptr(), python.len() as u64)).into()
}

pub fn identify(val: &Value) -> Ident {
  with_externs(|e| (e.identify)(e.context, val))
}

pub fn equals(val1: &Value, val2: &Value) -> bool {
  with_externs(|e| (e.equals)(e.context, val1, val2))
}

pub fn key_for(val: Value) -> Key {
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
  with_externs(|e| (e.drop_handles)(e.context, handles.as_ptr(), handles.len() as u64))
}

pub fn satisfied_by(constraint: &TypeConstraint, obj: &Value) -> bool {
  let interns = INTERNS.read().unwrap();
  with_externs(|e| (e.satisfied_by)(e.context, interns.get(&constraint.0), obj))
}

pub fn satisfied_by_type(constraint: &TypeConstraint, cls: &TypeId) -> bool {
  let interns = INTERNS.read().unwrap();
  with_externs(|e| (e.satisfied_by_type)(e.context, interns.get(&constraint.0), cls))
}

pub fn store_tuple(values: &[Value]) -> Value {
  with_externs(|e| (e.store_tuple)(e.context, values.as_ptr(), values.len() as u64))
}

pub fn store_bytes(bytes: &[u8]) -> Value {
  with_externs(|e| (e.store_bytes)(e.context, bytes.as_ptr(), bytes.len() as u64))
}

pub fn store_i64(val: i64) -> Value {
  with_externs(|e| (e.store_i64)(e.context, val))
}

pub fn project_ignoring_type(value: &Value, field: &str) -> Value {
  with_externs(|e| (e.project_ignoring_type)(e.context, value, field.as_ptr(), field.len() as u64))
}

pub fn project_multi(value: &Value, field: &str) -> Vec<Value> {
  with_externs(|e| (e.project_multi)(e.context, value, field.as_ptr(), field.len() as u64).to_vec())
}

pub fn project_multi_strs(item: &Value, field: &str) -> Vec<String> {
  project_multi(item, field)
    .iter()
    .map(|v| val_to_str(v))
    .collect()
}

pub fn project_str(value: &Value, field: &str) -> String {
  let name_val = with_externs(|e| {
    (e.project_ignoring_type)(e.context, value, field.as_ptr(), field.len() as u64)
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
    (e.val_to_str)(e.context, val)
      .to_string()
      .unwrap_or_else(|e| format!("<failed to decode unicode for {:?}: {}>", val, e))
  })
}

pub fn create_exception(msg: &str) -> Value {
  with_externs(|e| (e.create_exception)(e.context, msg.as_ptr(), msg.len() as u64))
}

pub fn call_method(value: &Value, method: &str, args: &[Value]) -> Result<Value, Failure> {
  call(&project_ignoring_type(&value, method), args)
}

pub fn call(func: &Value, args: &[Value]) -> Result<Value, Failure> {
  with_externs(|e| (e.call)(e.context, func, args.as_ptr(), args.len() as u64)).into()
}

pub fn generator_send(generator: &Value, arg: &Value) -> Result<GeneratorResponse, Failure> {
  let response = with_externs(|e| (e.generator_send)(e.context, generator, arg));
  match response.res_type {
    PyGeneratorResponseType::Break => Ok(GeneratorResponse::Break(response.values.unwrap_one())),
    PyGeneratorResponseType::Throw => Err(PyResult::failure_from(response.values.unwrap_one())),
    PyGeneratorResponseType::Get => {
      let mut interns = INTERNS.write().unwrap();
      let constraint = TypeConstraint(interns.insert(response.constraints.unwrap_one()));
      Ok(GeneratorResponse::Get(Get(
        constraint,
        interns.insert(response.values.unwrap_one()),
      )))
    }
    PyGeneratorResponseType::GetMulti => {
      let mut interns = INTERNS.write().unwrap();
      let continues = response
        .constraints
        .to_vec()
        .into_iter()
        .zip(response.values.to_vec().into_iter())
        .map(|(c, v)| Get(TypeConstraint(interns.insert(c)), interns.insert(v)))
        .collect();
      Ok(GeneratorResponse::GetMulti(continues))
    }
  }
}

///
/// NB: Panics on failure. Only recommended for use with built-in functions, such as
/// those configured in types::Types.
///
pub fn unsafe_call(func: &Function, args: &[Value]) -> Value {
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
  static ref INTERNS: RwLock<Interns> = RwLock::new(Interns::new());
}

// This is mut so that the max level can be set via set_externs.
// It should only be set exactly once, and nothing should ever read it (it is only defined to
// prevent the FfiLogger from being dropped).
// In order to avoid a performance hit, there is no lock guarding it (because if it had a lock, it
// would need to be acquired for every single logging statement).
// Please don't mutate it.
// Please.
static mut LOGGER: FfiLogger = FfiLogger {
  level_filter: log::LevelFilter::Off,
};

///
/// Set the static Externs for this process. All other methods of this module will fail
/// until this has been called.
///
pub fn set_externs(externs: Externs) {
  let log_level = externs.log_level;
  let mut externs_ref = EXTERNS.write().unwrap();
  *externs_ref = Some(externs);
  unsafe {
    LOGGER.init(log_level);
  }
}

fn with_externs<F, T>(f: F) -> T
where
  F: FnOnce(&Externs) -> T,
{
  let externs_opt = EXTERNS.read().unwrap();
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
  pub log: LogExtern,
  pub call: CallExtern,
  pub generator_send: GeneratorSendExtern,
  pub eval: EvalExtern,
  pub identify: IdentifyExtern,
  pub equals: EqualsExtern,
  pub clone_val: CloneValExtern,
  pub drop_handles: DropHandlesExtern,
  pub satisfied_by: SatisfiedByExtern,
  pub satisfied_by_type: SatisfiedByTypeExtern,
  pub store_tuple: StoreTupleExtern,
  pub store_bytes: StoreBytesExtern,
  pub store_i64: StoreI64Extern,
  pub project_ignoring_type: ProjectIgnoringTypeExtern,
  pub project_multi: ProjectMultiExtern,
  pub type_to_str: TypeToStrExtern,
  pub val_to_str: ValToStrExtern,
  pub create_exception: CreateExceptionExtern,
  // TODO: This type is also declared on `types::Types`.
  pub py_str_type: TypeId,
}

// The pointer to the context is safe for sharing between threads.
unsafe impl Sync for Externs {}
unsafe impl Send for Externs {}

pub type LogExtern = extern "C" fn(*const ExternContext, u8, str_ptr: *const u8, str_len: u64);

pub type SatisfiedByExtern =
  extern "C" fn(*const ExternContext, *const Value, *const Value) -> bool;

pub type SatisfiedByTypeExtern =
  extern "C" fn(*const ExternContext, *const Value, *const TypeId) -> bool;

pub type IdentifyExtern = extern "C" fn(*const ExternContext, *const Value) -> Ident;

pub type EqualsExtern = extern "C" fn(*const ExternContext, *const Value, *const Value) -> bool;

pub type CloneValExtern = extern "C" fn(*const ExternContext, *const Value) -> Value;

pub type DropHandlesExtern = extern "C" fn(*const ExternContext, *const Handle, u64);

pub type StoreTupleExtern = extern "C" fn(*const ExternContext, *const Value, u64) -> Value;

pub type StoreBytesExtern = extern "C" fn(*const ExternContext, *const u8, u64) -> Value;

pub type StoreI64Extern = extern "C" fn(*const ExternContext, i64) -> Value;

#[repr(C)]
#[derive(Debug)]
pub struct PyResult {
  is_throw: bool,
  value: Value,
}

impl PyResult {
  fn failure_from(v: Value) -> Failure {
    let traceback = project_str(&v, "_formatted_exc");
    Failure::Throw(v, traceback)
  }
}

impl From<PyResult> for Result<Value, Failure> {
  fn from(result: PyResult) -> Self {
    if result.is_throw {
      Err(PyResult::failure_from(result.value))
    } else {
      Ok(result.value)
    }
  }
}

impl From<Result<Value, String>> for PyResult {
  fn from(res: Result<Value, String>) -> Self {
    match res {
      Ok(v) => PyResult {
        is_throw: false,
        value: v,
      },
      Err(msg) => PyResult {
        is_throw: true,
        value: create_exception(&msg),
      },
    }
  }
}

impl From<Result<(), String>> for PyResult {
  fn from(res: Result<(), String>) -> Self {
    PyResult::from(res.map(|()| eval("None").unwrap()))
  }
}

// Only constructed from the python side.
#[allow(dead_code)]
#[repr(u8)]
pub enum PyGeneratorResponseType {
  Break = 0,
  Throw = 1,
  Get = 2,
  GetMulti = 3,
}

#[repr(C)]
pub struct PyGeneratorResponse {
  res_type: PyGeneratorResponseType,
  values: ValueBuffer,
  constraints: ValueBuffer,
}

#[derive(Debug)]
pub struct Get(pub TypeConstraint, pub Key);

pub enum GeneratorResponse {
  Break(Value),
  Get(Get),
  GetMulti(Vec<Get>),
}

// The result of an `identify` call, including the __hash__ of a Value and its TypeId.
#[repr(C)]
pub struct Ident {
  pub hash: i64,
  pub value: Value,
  pub type_id: TypeId,
}

///
/// Points to an array containing a series of values allocated by Python.
///
/// TODO: An interesting optimization might be possible where we avoid actually
/// allocating the values array for values_len == 1, and instead store the Value in
/// the `handle_` field.
///
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

  /// Asserts that the ValueBuffer contains one value, and returns it.
  pub fn unwrap_one(&self) -> Value {
    assert!(
      self.values_len == 1,
      "ValueBuffer contained more than one value: {}",
      self.values_len
    );
    with_vec(
      self.values_ptr,
      self.values_len as usize,
      |value_vec| unsafe { value_vec.iter().next().unwrap().clone_without_handle() },
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

pub type ProjectIgnoringTypeExtern =
  extern "C" fn(*const ExternContext, *const Value, field_name_ptr: *const u8, field_name_len: u64)
    -> Value;

pub type ProjectMultiExtern =
  extern "C" fn(*const ExternContext, *const Value, field_name_ptr: *const u8, field_name_len: u64)
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

pub type TypeToStrExtern = extern "C" fn(*const ExternContext, TypeId) -> Buffer;

pub type ValToStrExtern = extern "C" fn(*const ExternContext, *const Value) -> Buffer;

pub type CreateExceptionExtern =
  extern "C" fn(*const ExternContext, str_ptr: *const u8, str_len: u64) -> Value;

pub type CallExtern =
  extern "C" fn(*const ExternContext, *const Value, *const Value, u64) -> PyResult;

pub type GeneratorSendExtern =
  extern "C" fn(*const ExternContext, *const Value, *const Value) -> PyGeneratorResponse;

pub type EvalExtern =
  extern "C" fn(*const ExternContext, python_ptr: *const u8, python_len: u64) -> PyResult;

pub fn with_vec<F, C, T>(c_ptr: *mut C, c_len: usize, f: F) -> T
where
  F: FnOnce(&Vec<C>) -> T,
{
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  mem::forget(cs);
  output
}

// This is a hard-coding of constants in the standard logging python package.
enum_from_primitive! {
#[derive(Debug, Eq, PartialEq)]
#[repr(u8)]
enum PythonLogLevel {
  NotSet = 0,
  // Trace doesn't exist in a Python world, so set it to "a bit lower than Debug".
  Trace = 5,
  Debug = 10,
  Info = 20,
  Warn = 30,
  Error = 40,
  Critical = 50,
}
}

impl From<log::Level> for PythonLogLevel {
  fn from(level: log::Level) -> Self {
    match level {
      log::Level::Error => PythonLogLevel::Error,
      log::Level::Warn => PythonLogLevel::Warn,
      log::Level::Info => PythonLogLevel::Info,
      log::Level::Debug => PythonLogLevel::Debug,
      log::Level::Trace => PythonLogLevel::Trace,
    }
  }
}

impl From<PythonLogLevel> for log::LevelFilter {
  fn from(level: PythonLogLevel) -> Self {
    match level {
      PythonLogLevel::NotSet => log::LevelFilter::Off,
      PythonLogLevel::Trace => log::LevelFilter::Trace,
      PythonLogLevel::Debug => log::LevelFilter::Debug,
      PythonLogLevel::Info => log::LevelFilter::Info,
      PythonLogLevel::Warn => log::LevelFilter::Warn,
      PythonLogLevel::Error => log::LevelFilter::Error,
      // Rust doesn't have a Critical, so treat them like Errors.
      PythonLogLevel::Critical => log::LevelFilter::Error,
    }
  }
}

///
/// FfiLogger is an implementation of log::Log which asks the Python logging system to log via cffi.
///
struct FfiLogger {
  level_filter: log::LevelFilter,
}

impl FfiLogger {
  // init must only be called once in the lifetime of the program. No other loggers may be init'd.
  // If either of the above are violated, expect a panic.
  pub fn init(&'static mut self, max_level: u8) {
    let max_python_level = PythonLogLevel::from_u8(max_level);
    self.level_filter = {
      match max_python_level {
        Some(python_level) => {
          let level: log::LevelFilter = python_level.into();
          level
        }
        None => panic!("Unrecognised log level from python: {}", max_level),
      }
    };

    log::set_max_level(self.level_filter);
    log::set_logger(self)
      .expect("Failed to set logger (maybe you tried to call init multiple times?)");
  }
}

impl log::Log for FfiLogger {
  fn enabled(&self, metadata: &log::Metadata) -> bool {
    metadata.level() >= self.level_filter
  }

  fn log(&self, record: &log::Record) {
    if !self.enabled(record.metadata()) {
      return;
    }
    let level: PythonLogLevel = record.level().into();
    let message = format!("{}", record.args());
    with_externs(|e| {
      (e.log)(
        e.context,
        level as u8,
        message.as_ptr(),
        message.len() as u64,
      )
    })
  }

  fn flush(&self) {}
}
