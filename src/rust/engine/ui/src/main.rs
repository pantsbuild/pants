// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
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
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(
  clippy::new_without_default,
  clippy::new_without_default_derive,
  clippy::new_ret_no_self
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use rand;

use std::thread;
use std::time::Duration;

use rand::Rng;

use ui::EngineDisplay;

// N.B. This is purely a demo/testing bin target for exercising the library.

fn main() {
  let mut display = EngineDisplay::for_stdout(0);
  display.start();

  let worker_ids = vec![
    "pool worker 1".to_string(),
    "pool worker 2".to_string(),
    "pool worker 3".to_string(),
    "pool worker 4".to_string(),
    "pool worker 5".to_string(),
    "pool worker 6".to_string(),
    "pool worker 7".to_string(),
    "pool worker 8".to_string(),
  ];

  let random_verbs = vec![
    "some printable result for".to_string(),
    "failed to get a".to_string(),
  ];

  let random_log_levels = vec!["INFO".to_string(), "WARN".to_string(), "DEBUG".to_string()];

  let random_products = vec!(
    "PathGlobs".to_string(),
    "FileContents xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxzzzzzzzzzzzzzzzzzzzzzzzzz".to_string(),
    "Snapshot".to_string(),
    "DirectoryDigest".to_string(),
    "SourcesField".to_string(),
    "BundlesField".to_string(),
    "HydratedField".to_string(),
    "File".to_string(),
    "Dir".to_string(),
    "Link".to_string()
  );

  let mut done = false;
  let mut counter: u64 = 0;

  for worker_id in worker_ids.clone() {
    display.add_worker(worker_id);
    display.render();
    thread::sleep(Duration::from_millis(63));
  }

  display.render();
  thread::sleep(Duration::from_secs(1));

  while !done {
    display.render_and_sleep();

    gen_display_work(
      &mut display,
      counter,
      &random_products,
      &worker_ids,
      &random_verbs,
      &random_log_levels,
    );

    if counter > 300 {
      done = true;
    } else {
      counter += 1;
    }
  }

  display.finish();
}

fn gen_display_work(
  display: &mut EngineDisplay,
  counter: u64,
  type_selection: &[String],
  worker_ids: &[String],
  verb_selection: &[String],
  log_level_selection: &[String],
) {
  let mut rng = rand::thread_rng();

  for worker_id in worker_ids {
    let random_product = rng.choose(&type_selection).unwrap();
    let random_subject = rng.choose(&type_selection).unwrap();

    display.update(
      worker_id.to_string(),
      format!("computing {} for {}(...)", random_product, random_subject),
    );
  }

  if counter > 50 && counter % 2 == 0 {
    let random_log_level = rng.choose(&log_level_selection).unwrap();
    let random_verb = rng.choose(&verb_selection).unwrap();
    let random_product_2 = rng.choose(&type_selection).unwrap();

    display.log(format!(
      "{}] {} {}",
      random_log_level, random_verb, random_product_2
    ));
  }
}
