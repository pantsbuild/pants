use std::{collections::HashSet, io::Write, path::PathBuf};

fn gen_constants_file() {
  let mut file = std::fs::File::create(PathBuf::from("src/python/constants.rs")).unwrap();

  file
    .write_all("#[non_exhaustive]\npub struct KindID;\n\n".as_bytes())
    .unwrap();
  file.write_all("impl KindID {\n".as_bytes()).unwrap();

  let python_lang = tree_sitter_python::language();
  let mut kinds_seen = HashSet::new();

  for id in 0..python_lang.node_kind_count() {
    let id = id as u16;
    if python_lang.node_kind_is_named(id) {
      let kind = python_lang.node_kind_for_id(id).unwrap().to_uppercase();
      if kinds_seen.insert(kind.to_string()) {
        file
          .write_all(format!("  pub const {kind}: u16 = {id};\n").as_bytes())
          .unwrap();
      }
    }
  }

  file.write_all("}\n".as_bytes()).unwrap();
}

fn gen_visitor_file() {
  let mut file = std::fs::File::create(PathBuf::from("src/python/visitor.rs")).unwrap();
  let python_lang = tree_sitter_python::language();

  file
    .write_all(
      r#"#[derive(Debug, PartialEq)]
pub enum ChildBehavior {
    Visit,
    Ignore,
}
"#
      .as_bytes(),
    )
    .unwrap();

  file
    .write_all("#[allow(unused_variables)]\npub trait Visitor {\n".as_bytes())
    .unwrap();

  let mut kinds_seen = HashSet::new();
  for id in 0..python_lang.node_kind_count() {
    let id = id as u16;
    if python_lang.node_kind_is_named(id) {
      let kind = python_lang.node_kind_for_id(id).unwrap();
      if kinds_seen.insert(kind.to_string()) {
        file.write_all(
                    format!("  fn visit_{kind}(&mut self, node: tree_sitter::Node) -> ChildBehavior {{ ChildBehavior::Visit }}\n")
                        .as_bytes(),
                )
                .unwrap();
      }
    }
  }

  file
    .write_all("\n  fn visit(&mut self, node: tree_sitter::Node) -> ChildBehavior {\n".as_bytes())
    .unwrap();
  file
    .write_all("      match node.kind_id() {\n".as_bytes())
    .unwrap();
  for id in 0..python_lang.node_kind_count() {
    let id = id as u16;
    if python_lang.node_kind_is_named(id) {
      let kind = python_lang.node_kind_for_id(id).unwrap();
      file
        .write_all(format!("        {id} => self.visit_{kind}(node),\n").as_bytes())
        .unwrap();
    }
  }
  file
    .write_all("        _ => ChildBehavior::Visit,\n".as_bytes())
    .unwrap();
  file.write_all("    }\n".as_bytes()).unwrap();
  file.write_all("  }\n".as_bytes()).unwrap();

  file.write_all("}\n".as_bytes()).unwrap();
}

fn main() {
  gen_constants_file();
  gen_visitor_file();
}
