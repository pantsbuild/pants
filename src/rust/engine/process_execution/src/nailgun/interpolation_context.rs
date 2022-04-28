use std::collections::BTreeMap;

/// Represents a context that can be used to transform strings interpolating
/// values stored internally in the context
#[derive(Default, PartialEq, Eq, Debug)]
pub struct InterpolationContext {
  ctx: BTreeMap<String, String>,
}

impl InterpolationContext {
  pub fn new() -> InterpolationContext {
    InterpolationContext {
      ctx: BTreeMap::new(),
    }
  }

  pub fn set(&mut self, key: String, value: String) -> &mut InterpolationContext {
    self.ctx.insert(key, value);
    self
  }

  pub fn format(&self, string: String) -> String {
    let mut result_str = string.clone();

    for (key, value) in &self.ctx {
      let mut pattern: String = "${".to_owned();
      pattern.push_str(&key);
      pattern.push_str("}");

      result_str = result_str.replace(&pattern, value);
    }

    return result_str;
  }
}
