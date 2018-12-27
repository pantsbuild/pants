// TODO: This is in its own file because of poor macro hygiene in starlark. Fixing starlark's
// macros should be easy.
use starlark::values::{TypedValue, Value, ValueError, ValueResult};

#[derive(PartialEq, Eq, Ord, PartialOrd)]
pub struct CallIndex(pub usize);

impl starlark::values::TypedValue for CallIndex {
  immutable!();
  any!();
  fn to_str(&self) -> String {
    format!("CallIndex({})", self.0)
  }
  fn to_repr(&self) -> String {
    self.to_str()
  }
  not_supported!(to_int);
  fn get_type(&self) -> &'static str {
    "CallIndex"
  }
  fn to_bool(&self) -> bool {
    false
  }
  fn get_hash(&self) -> Result<u64, ValueError> {
    Ok(self.0 as u64)
  }
  fn compare(
    &self,
    other: &starlark::values::TypedValue,
    _recursion: u32,
  ) -> Result<std::cmp::Ordering, starlark::values::ValueError> {
    match other.get_type() {
      "CallIndex" => {
        let other = other.as_any().downcast_ref::<Self>().unwrap();
        Ok(std::cmp::Ord::cmp(self, other))
      }
      _ => starlark::values::default_compare(self, other),
    }
  }
  not_supported!(binop);
  not_supported!(container);
  not_supported!(function);
}
