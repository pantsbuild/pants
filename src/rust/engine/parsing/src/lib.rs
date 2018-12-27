// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(clippy::len_without_is_empty, clippy::redundant_field_names)]
// Default isn't as big a deal as people seem to think it is.
#![allow(
  clippy::new_without_default,
  clippy::new_without_default_derive,
  clippy::new_ret_no_self
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

#[macro_use]
extern crate starlark;

// LinkedHashMap not IndexMap because LinkedHashMap implements Hash.
// TODO: Do a decent audit of the two to decide which we should generally be using.
use linked_hash_map::LinkedHashMap;
use linked_hash_set::LinkedHashSet;
use parking_lot::Mutex;
use std::borrow::Borrow;
use std::path::Path;
use std::rc::Rc;
use std::sync::Arc;

mod call_index;
use self::call_index::CallIndex;

#[derive(Debug, PartialEq, Eq)]
pub struct Call {
  pub function_name: String,
  pub args: Vec<Value>,
  pub kwargs: Vec<(String, Value)>,
}

#[derive(Debug, PartialEq, Eq, Hash)]
pub enum Value {
  Bool(bool),
  Dict(LinkedHashMap<Value, Value>),
  String(String),
  List(Vec<Value>),
  Set(LinkedHashSet<Value>),
  Number(i64),
  CallIndex(usize),
  Function(String),
}

impl Value {
  fn from(v: &starlark::values::Value) -> Result<Value, String> {
    match v.get_type() {
      "bool" => Ok(Value::Bool(v.to_bool())),
      "dict" => starlark::values::dict::Dictionary::apply(&v, &|map| {
        map
          .iter()
          .map(|(k, v)| {
            Ok((
              Value::from(k).map_err(string_to_valueerror)?,
              Value::from(v).map_err(string_to_valueerror)?,
            ))
          })
          .collect::<Result<LinkedHashMap<_, _>, _>>()
      })
      .map(Value::Dict)
      .map_err(|err| format!("Error converting dict from starlark: {:?}", err)),
      "string" => Ok(Value::String(v.to_str())),
      "int" => Ok(Value::Number(v.to_int().unwrap())),
      "list" => v
        .iter()
        .unwrap()
        .map(|v| Value::from(&v))
        .collect::<Result<Vec<_>, _>>()
        .map(Value::List),
      "set" => v
        .iter()
        .unwrap()
        .map(|v| Value::from(&v))
        .collect::<Result<LinkedHashSet<_>, _>>()
        .map(Value::Set),
      "CallIndex" => {
        Ok(Value::CallIndex(v.any_apply(&|any| {
          any.downcast_ref::<CallIndex>().unwrap().0
        })))
      }
      "function" => Ok(Value::Function(v.any_apply(&|any| {
        any
          .downcast_ref::<starlark::values::function::Function>()
          .unwrap()
          .name()
      }))),
      other => Err(format!("Unknown type: {} ({})", other, v.to_str())),
    }
  }
}

fn string_to_valueerror(message: String) -> starlark::values::ValueError {
  starlark::values::RuntimeError {
    code: starlark::values::NOT_SUPPORTED_ERROR_CODE,
    message: message,
    label: String::new(),
  }
  .into()
}

// TODO: Accept function signatures, and check them
pub fn parse(
  function_list: &[String],
  to_parse: &str,
  build_file_path: &Path,
  buildroot: &Path,
) -> Result<Vec<Call>, String> {
  let calls = Rc::new(Mutex::new(vec![]));

  {
    let mut env = make_env(function_list, &calls, build_file_path, buildroot);
    starlark::eval::eval(
      &Arc::new(std::sync::Mutex::new(codemap::CodeMap::new())),
      build_file_path.to_string_lossy().borrow(),
      to_parse,
      starlark::syntax::dialect::Dialect::Bzl,
      &mut env,
      (),
    )
    .map_err(|err| format!("Error parsing {}: {:?}", build_file_path.display(), err))?;
  }

  Ok(Rc::try_unwrap(calls).unwrap().into_inner())
}

fn make_env(
  function_list: &[String],
  calls: &Rc<Mutex<Vec<Call>>>,
  build_file_path: &Path,
  buildroot: &Path,
) -> starlark::environment::Environment {
  let mut env = starlark::stdlib::global_environment();

  // These functions don't _need_ to be registered here (they could just be mirroring functions as
  // the rest are), but are here to show what actual native implementations may look like.

  env
    .set(
      "buildfile_path",
      const_fn(
        "buildfile_path".to_owned(),
        starlark::values::Value::new(
          buildroot
            .join(build_file_path)
            .to_string_lossy()
            .into_owned(),
        ),
      ),
    )
    .unwrap();
  env
    .set(
      "get_buildroot",
      const_fn(
        "get_buildroot".to_owned(),
        starlark::values::Value::new(buildroot.to_string_lossy().into_owned()),
      ),
    )
    .unwrap();

  for function in function_list {
    if function == "*buildfile_path" || function == "get_buildroot" {
      continue;
    }
    register_fn(&function, calls.clone(), &mut env);
  }

  env
}

fn const_fn(name: String, value: starlark::values::Value) -> starlark::values::Value {
  starlark::values::function::Function::new(name, move |_, _, _| Ok(value.clone()), vec![])
}

fn register_fn(
  name: &str,
  calls: Rc<Mutex<Vec<Call>>>,
  env: &mut starlark::environment::Environment,
) {
  let f = fun(name.to_owned(), calls);
  env.set(name, f).unwrap();
}

// Returns a callable function which takes any args and kwargs, and records that it was called (and
// what arguments it was called with) to pass up to Python so that Python code can call the function
// with the same name and args.
fn fun(name: String, calls: Rc<Mutex<Vec<Call>>>) -> starlark::values::Value {
  starlark::values::function::Function::new(
    name.clone(),
    move |_, _, mut args| {
      let calls = calls.clone();
      let kwargs = args.pop().unwrap();

      let mut kwargs_vec = vec![];
      for key in kwargs.iter().unwrap() {
        let key_str = key.to_str();
        let value = kwargs.at(key.clone()).unwrap();
        kwargs_vec.push((key_str, Value::from(&value).map_err(string_to_valueerror)?));
      }

      let args = args.pop().unwrap();
      let mut args_vec = vec![];
      for arg in args.iter().unwrap() {
        args_vec.push(Value::from(&arg).map_err(string_to_valueerror)?);
      }

      let mut calls = calls.lock();
      let id = calls.len() as u64;
      calls.push(Call {
        function_name: name.clone(),
        args: args_vec,
        kwargs: kwargs_vec,
      });
      Ok(starlark::values::Value::new(CallIndex(id as usize)))
    },
    vec![
      starlark::values::function::FunctionParameter::ArgsArray("args".to_owned()),
      starlark::values::function::FunctionParameter::KWArgsDict("kwargs".to_owned()),
    ],
  )
}

#[cfg(test)]
mod test {
  use super::*;
  use std::path::PathBuf;

  #[test]
  fn simple_call() {
    let want = vec![Call {
      function_name: "fn1".to_owned(),
      args: vec![Value::String("hello".to_owned()), Value::Number(1)],
      kwargs: vec![],
    }];
    let got = parse(
      &["fn1".to_owned()],
      r#"fn1("hello", 1)"#,
      &PathBuf::from("some/BUILD"),
      &PathBuf::from("/tmp/buildroot"),
    );
    assert_eq!(got, Ok(want));
  }

  #[test]
  fn get_buildroot() {
    let build_file_path = PathBuf::from("path/to/BUILD");
    let buildroot = PathBuf::from("/tmp/buildroot");

    let mut env = make_env(
      &[],
      &Rc::new(Mutex::new(Vec::new())),
      &build_file_path,
      &buildroot,
    );

    let value = starlark::eval::eval(
      &Arc::new(Mutex::new(codemap::CodeMap::new())),
      build_file_path.to_string_lossy().borrow(),
      "get_buildroot()",
      false,
      &mut env,
      (),
    )
    .expect("Error evaling");

    assert_eq!(
      value,
      starlark::values::Value::new("/tmp/buildroot".to_owned())
    );
  }

  #[test]
  fn buildfile_path() {
    let build_file_path = PathBuf::from("path/to/BUILD");
    let buildroot = PathBuf::from("/tmp/buildroot");

    let mut env = make_env(
      &[],
      &Rc::new(Mutex::new(Vec::new())),
      &build_file_path,
      &buildroot,
    );

    let value = starlark::eval::eval(
      &Arc::new(Mutex::new(codemap::CodeMap::new())),
      build_file_path.to_string_lossy().borrow(),
      "buildfile_path()",
      false,
      &mut env,
      (),
    )
    .expect("Error evaling");

    assert_eq!(
      value,
      starlark::values::Value::new("/tmp/buildroot/path/to/BUILD".to_owned())
    );
  }

  #[test]
  fn format() {
    let build_file_path = PathBuf::from("path/to/BUILD");
    let buildroot = PathBuf::from("/tmp/buildroot");

    let mut env = make_env(
      &[],
      &Rc::new(Mutex::new(Vec::new())),
      &build_file_path,
      &buildroot,
    );

    let value = starlark::eval::eval(
      &Arc::new(Mutex::new(codemap::CodeMap::new())),
      build_file_path.to_string_lossy().borrow(),
      "'{}'.format(get_buildroot())",
      false,
      &mut env,
      (),
    )
    .expect("Error evaling");

    assert_eq!(
      value,
      starlark::values::Value::new("/tmp/buildroot".to_owned())
    );
  }
}
