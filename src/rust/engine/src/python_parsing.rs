#![allow(dead_code)]
#![allow(unused_variables)]

use dep_inference::python::ImportCollector;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::collections::HashSet;
use std::path::PathBuf;

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
  let path_parts: Vec<String> = filepath
    .parent()
    .unwrap()
    .iter()
    .map(|p| p.to_str().unwrap().to_string())
    .collect();
  for key in keys_to_replace {
    let nonrelative = key.trim_start_matches('.').to_string();
    let level = key.len() - nonrelative.len();
    let mut new_key = if level > path_parts.len() {
      // Just put back the prefix, this went above the parent
      key[0..level].to_string()
    } else {
      path_parts[0..((path_parts.len() - level) + 1)].join(".") + "."
    };
    new_key.push_str(nonrelative.as_str());

    println!("Replacing {key:?} with {new_key:?} and level was {level:?}");
    let old_value = import_map.remove(&key).unwrap();
    import_map.insert(new_key, old_value);
  }

  Ok(ParsedPythonDependencies {
    imports: import_map,
    string_candidates: collector.string_candidates,
  })
}
