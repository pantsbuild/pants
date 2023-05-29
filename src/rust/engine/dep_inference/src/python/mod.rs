// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::path::PathBuf;

include!(concat!(env!("OUT_DIR"), "/constants.rs"));
include!(concat!(env!("OUT_DIR"), "/visitor.rs"));

use fnv::{FnvHashMap as HashMap, FnvHashSet as HashSet};
use serde_derive::{Deserialize, Serialize};
use tree_sitter::Parser;

#[derive(Serialize, Deserialize)]
pub struct ParsedPythonDependencies {
  pub imports: HashMap<String, (u64, bool)>,
  pub string_candidates: HashMap<String, u64>,
}

pub fn get_dependencies(
  contents: &str,
  filepath: PathBuf,
) -> Result<ParsedPythonDependencies, String> {
  let mut collector = ImportCollector::new(contents);
  collector.collect();

  let mut import_map = collector.import_map;

  // NB: the import collector doesn't do anything special for relative imports, we need to fix
  // those up.
  let keys_to_replace: HashSet<_> = import_map
    .keys()
    .filter(|key| key.starts_with('.'))
    .cloned()
    .collect();
  let parent_path = filepath
    .parent()
    .expect("Expected a filepath that was non-root");
  let path_parts: Vec<&str> = parent_path
    .iter()
    .map(|p| {
      p.to_str()
        .expect("Expected UTF-8-compatible filepath parts")
    })
    .collect();
  for key in keys_to_replace {
    let nonrelative = key.trim_start_matches('.');
    let level = key.len() - nonrelative.len();
    if level > path_parts.len() {
      // Don't mess with the key, let Pants error with the original string
      continue;
    }

    let mut new_key_parts = path_parts[0..((path_parts.len() - level) + 1)].to_vec();
    new_key_parts.push(nonrelative);

    let old_value = import_map.remove(&key).unwrap();
    import_map.insert(new_key_parts.join("."), old_value);
  }

  Ok(ParsedPythonDependencies {
    imports: import_map,
    string_candidates: collector.string_candidates,
  })
}

struct ImportCollector<'a> {
  pub import_map: HashMap<String, (u64, bool)>,
  pub string_candidates: HashMap<String, u64>,
  code: &'a str,
  weaken_imports: bool,
}

impl ImportCollector<'_> {
  pub fn new(code: &'_ str) -> ImportCollector<'_> {
    ImportCollector {
      import_map: HashMap::default(),
      string_candidates: HashMap::default(),
      code,
      weaken_imports: false,
    }
  }

  pub fn collect(&mut self) {
    let mut parser = Parser::new();
    parser
      .set_language(tree_sitter_python::language())
      .expect("Error loading Python grammar");
    let parsed = parser.parse(self.code, None);
    let tree = parsed.unwrap();
    let mut cursor = tree.walk();

    self.walk(&mut cursor);
  }

  fn walk(&mut self, cursor: &mut tree_sitter::TreeCursor) {
    loop {
      let node = cursor.node();
      let children_behavior = self.visit(node);

      if children_behavior == ChildBehavior::Visit && cursor.goto_first_child() {
        continue;
      }
      // NB: Could post_visit(node) here

      if cursor.goto_next_sibling() {
        continue;
      }

      let mut at_root = false;
      while !at_root {
        if cursor.goto_parent() {
          // NB: Could post_visit(cursor.node()) here
          if cursor.goto_next_sibling() {
            break;
          }
        } else {
          at_root = true
        }
      }
      if at_root {
        break;
      }
    }
  }

  fn code_at(&self, range: tree_sitter::Range) -> &str {
    &self.code[range.start_byte..range.end_byte]
  }

  fn string_at(&self, range: tree_sitter::Range) -> &str {
    // https://docs.python.org/3/reference/lexical_analysis.html#string-and-bytes-literals
    self
      .code_at(range)
      .trim_start_matches(|c| "rRuUfFbB".contains(c))
      .trim_matches(|c| "'\"".contains(c))
  }

  fn is_pragma_ignored(&self, node: tree_sitter::Node) -> bool {
    if let Some(sibling) = node.next_named_sibling() {
      let next_node_range = sibling.range();
      if sibling.kind_id() == KindID::COMMENT
        && node.range().end_point.row == next_node_range.start_point.row
        && self
          .code_at(next_node_range)
          .contains("# pants: no-infer-dep")
      {
        return true;
      }
    }
    false
  }

  fn insert_import(
    &mut self,
    name: tree_sitter::Node,
    module_name: Option<tree_sitter::Node>,
    is_string: bool,
  ) {
    let dotted_name = match name.kind_id() {
      KindID::ALIASED_IMPORT => name
        .named_child(0)
        .expect("Expected named child of aliased_import while parsing Python file."),
      KindID::ERROR => {
        return;
      }
      _ => name,
    };
    let name_range = dotted_name.range();

    if self.is_pragma_ignored(name) {
      return;
    }

    let name_ref = if is_string {
      self.string_at(name_range)
    } else {
      self.code_at(name_range)
    };
    let full_name = match module_name {
      Some(module_name) => {
        let mod_text = self.code_at(module_name.range());
        // `from ... import a` => `...a` mod_text alone, but `from x import a` => `x.a` needs to
        // insert a .
        let joiner = if mod_text.ends_with('.') { "" } else { "." };
        [mod_text, name_ref].join(joiner)
      }
      None => name_ref.to_string(),
    };

    self
      .import_map
      .entry(full_name)
      .and_modify(|v| *v = (v.0, v.1 && self.weaken_imports))
      .or_insert(((name_range.start_point.row as u64) + 1, self.weaken_imports));
  }
}

// NB: https://tree-sitter.github.io/tree-sitter/playground is very helpful
impl Visitor for ImportCollector<'_> {
  fn visit_import_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior {
    if !self.is_pragma_ignored(node) {
      self.insert_import(node.named_child(0).unwrap(), None, false);
    }
    ChildBehavior::Ignore
  }

  fn visit_import_from_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior {
    if !self.is_pragma_ignored(node) {
      for child in node.children_by_field_name("name", &mut node.walk()) {
        self.insert_import(child, Some(node.named_child(0).unwrap()), false);
      }
    }
    ChildBehavior::Ignore
  }

  // @TODO: If we wanted to be most correct, this should use a stack. But realistically, that's
  // kinda complicated:
  // try:
  //   try:
  //       import weak1
  //   except Whatever:
  //       ...
  //   import weak2
  // except ImportError:
  //   ...
  fn visit_try_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior {
    let mut should_weaken = false;
    let mut cursor = node.walk();
    let children: Vec<_> = node.named_children(&mut cursor).collect();
    for child in children.iter() {
      if child.kind_id() == KindID::EXCEPT_CLAUSE {
        // N.B. Python allows any arbitrary expression as an except handler.
        // We only parse identifiers, or (Set/Tuple/List)-of-identifier expressions.
        let except_expr = child.named_child(0).unwrap();
        should_weaken = match except_expr.kind_id() {
          KindID::IDENTIFIER => self.code_at(except_expr.range()) == "ImportError",
          KindID::SET | KindID::LIST | KindID::TUPLE => except_expr
            .named_children(&mut except_expr.walk())
            .any(|expr| {
              expr.kind_id() == KindID::IDENTIFIER && self.code_at(expr.range()) == "ImportError"
            }),
          _ => false,
        };
        if should_weaken {
          break;
        }
      }
    }

    for child in children.iter() {
      if child.kind_id() == KindID::BLOCK {
        self.weaken_imports = should_weaken;
      }
      self.walk(&mut child.walk());
      self.weaken_imports = false;
    }
    ChildBehavior::Ignore
  }

  fn visit_call(&mut self, node: tree_sitter::Node) -> ChildBehavior {
    let funcname = node.named_child(0).unwrap();
    if self.code_at(funcname.range()) != "__import__" {
      return ChildBehavior::Visit;
    }

    let args = node.named_child(1).unwrap();
    if let Some(arg) = args.named_child(0) {
      if arg.kind_id() == KindID::STRING {
        // NB: Call nodes are children of expression nodes. The comment is a sibling of the expression.
        if !self.is_pragma_ignored(node.parent().unwrap()) {
          self.insert_import(arg, None, true);
        }
      }
    }
    ChildBehavior::Ignore
  }

  fn visit_string(&mut self, node: tree_sitter::Node) -> ChildBehavior {
    let range = node.range();
    let text: &str = self.string_at(range);
    if !text.contains(|c: char| c.is_ascii_whitespace() || c == '\\') {
      self
        .string_candidates
        .insert(text.to_string(), (range.start_point.row + 1) as u64);
    }
    ChildBehavior::Ignore
  }
}

#[cfg(test)]
mod tests;
