extern crate engine_display;
extern crate rand;

use std::thread;
use std::time::Duration;

use rand::Rng;

use engine_display::EngineDisplay;

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

  fn gen_display_work(
    display: &mut EngineDisplay,
    counter: &u64,
    type_selection: &Vec<String>,
    worker_ids: &Vec<String>,
    verb_selection: &Vec<String>,
    log_level_selection: &Vec<String>,
  ) {
    let mut rng = rand::thread_rng();

    for worker_id in worker_ids.clone().into_iter() {
      let random_product = rng.choose(&type_selection).unwrap();
      let random_subject = rng.choose(&type_selection).unwrap();

      display.update(
        worker_id,
        String::from(format!(
          "computing {} for {}(...)",
          random_product, random_subject
        )),
      );
    }

    if counter > &50 && counter % 2 == 0 {
      let random_log_level = rng.choose(&log_level_selection).unwrap();
      let random_verb = rng.choose(&verb_selection).unwrap();
      let random_product_2 = rng.choose(&type_selection).unwrap();

      display.log(format!(
        "{}] {} {}",
        random_log_level, random_verb, random_product_2
      ));
    }
  }

  let mut done = false;
  let mut counter: u64 = 0;

  for worker_id in worker_ids.clone().into_iter() {
    display.add_worker(String::from(worker_id));
    display.render();
    thread::sleep(Duration::from_millis(63));
  }

  display.render();
  thread::sleep(Duration::from_secs(1));

  while !done {
    display.render_and_sleep();

    gen_display_work(
      &mut display,
      &counter,
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
