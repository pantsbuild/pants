// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fs::File;
use std::io::Write;

use crate::config::Config;
use crate::{option_id, OptionId, OptionsSource};

use tempfile::TempDir;

fn config<I: IntoIterator<Item = &'static str>>(file_contents: I) -> Config {
  let dir = TempDir::new().unwrap();
  let files = file_contents
    .into_iter()
    .enumerate()
    .map(|(idx, file_content)| {
      let path = dir.path().join(format!("{idx}.toml"));
      File::create(&path)
        .unwrap()
        .write_all(file_content.as_bytes())
        .unwrap();
      path
    })
    .collect::<Vec<_>>();
  Config::merged(&files).unwrap()
}

#[test]
fn test_display() {
  let config = config([]);
  assert_eq!(
    "[GLOBAL] name".to_owned(),
    config.display(&option_id!("name"))
  );
  assert_eq!(
    "[scope] name".to_owned(),
    config.display(&option_id!(["scope"], "name"))
  );
  assert_eq!(
    "[scope] full_name".to_owned(),
    config.display(&option_id!(-'f', ["scope"], "full", "name"))
  );
}

#[test]
fn test_section_overlap() {
  // Two files with the same section should result in merged content for that section.
  let config = config([
    "[section]\n\
     field1 = 'something'\n",
    "[section]\n\
     field2 = 'something else'\n",
  ]);

  let assert_string = |expected: &str, id: OptionId| {
    assert_eq!(
      expected.to_owned(),
      config.get_string(&id).unwrap().unwrap()
    )
  };

  assert_string("something", option_id!(["section"], "field1"));
  assert_string("something else", option_id!(["section"], "field2"));
}
