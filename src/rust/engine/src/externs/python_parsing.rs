use rustpython_parser::ast;
use rustpython_parser::parser::parse_program;
use std::collections::HashMap;

pub fn get_dependencies(
  contents: &str,
  filepath: &str,
) -> Result<HashMap<String, (u64, bool)>, String> {
  let program =
    parse_program(contents, filepath).map_err(|e| format!("Failed to parse file <BLAH>: {e}"))?;

  let mut result = HashMap::new();
  visit_stmts(&program, filepath, &mut result);

  Ok(result)
}

fn visit_stmts(stmts: &[ast::Stmt], filepath: &str, import_map: &mut HashMap<String, (u64, bool)>) {
  for stmt in stmts.iter() {
    visit_stmt(stmt, filepath, import_map);
  }
}

fn visit_stmt(stmt: &ast::Stmt, filepath: &str, import_map: &mut HashMap<String, (u64, bool)>) {
  match &stmt.node {
    ast::StmtKind::FunctionDef { body, .. } => visit_stmts(body, filepath, import_map),
    ast::StmtKind::AsyncFunctionDef { body, .. } => visit_stmts(body, filepath, import_map),
    ast::StmtKind::ClassDef { body, .. } => visit_stmts(body, filepath, import_map),
    ast::StmtKind::For { body, orelse, .. } => {
      visit_stmts(body, filepath, import_map);
      visit_stmts(orelse, filepath, import_map);
    }
    ast::StmtKind::AsyncFor { body, orelse, .. } => {
      visit_stmts(body, filepath, import_map);
      visit_stmts(orelse, filepath, import_map);
    }
    ast::StmtKind::While { body, orelse, .. } => {
      visit_stmts(body, filepath, import_map);
      visit_stmts(orelse, filepath, import_map);
    }
    ast::StmtKind::If { body, orelse, .. } => {
      visit_stmts(body, filepath, import_map);
      visit_stmts(orelse, filepath, import_map);
    }
    ast::StmtKind::With { body, .. } => visit_stmts(body, filepath, import_map),
    ast::StmtKind::AsyncWith { body, .. } => visit_stmts(body, filepath, import_map),
    ast::StmtKind::Match { cases, .. } => {
      for case in cases.iter() {
        visit_stmts(&case.body, filepath, import_map);
      }
    }
    // These also need to look at handlers, each handler.body
    ast::StmtKind::Try {
      handlers,
      orelse,
      finalbody,
      ..
    } => {
      visit_stmts(orelse, filepath, import_map);
      visit_stmts(finalbody, filepath, import_map);
      for handler in handlers.iter() {
        match &handler.node {
          ast::ExcepthandlerKind::ExceptHandler { body, .. } => {
            visit_stmts(body, filepath, import_map)
          }
        }
      }
    }
    // TODO: Support ast::StmtKind::TryStar when 3.11 support is added
    ast::StmtKind::Import { names, .. } => {
      for located_alias in names {
        import_map.insert(
          located_alias.node.name.clone(),
          (located_alias.location.row().try_into().unwrap(), false),
        );
      }
    }
    ast::StmtKind::ImportFrom {
      module,
      names,
      level,
    } => {
      let abs_module = match level {
        Some(level) => {
          let mut path_parts: Vec<&str> = filepath.split('/').collect();
          path_parts.truncate(path_parts.len() - level + 1);
          if module.is_some() {
            path_parts.push(module.as_ref().unwrap());
          }
          path_parts.join(".")
        }
        None => module.clone().unwrap(),
      };
      for located_alias in names {
        let modname = vec![abs_module.clone(), located_alias.node.name.clone()].join(".");
        import_map.insert(
          modname,
          (located_alias.location.row().try_into().unwrap(), false),
        );
      }
    }
    _ => {}
  }
}
