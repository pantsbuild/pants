// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::future::Future;
use std::pin::Pin;
use std::sync::mpsc;
use std::time::Duration;

use futures::future::{self, FutureExt, TryFutureExt};
use indexmap::IndexMap;
use indicatif::{MultiProgress, ProgressBar, ProgressDrawTarget, ProgressStyle};

use task_executor::Executor;
use workunit_store::{format_workunit_duration, WorkunitStore};

pub struct ConsoleUI {
  workunit_store: WorkunitStore,
  local_parallelism: usize,
  // While the UI is running, there will be an Instance present.
  instance: Option<Instance>,
  teardown_in_progress: bool,
  teardown_mpsc: (mpsc::Sender<()>, mpsc::Receiver<()>),
}

impl ConsoleUI {
  pub fn new(workunit_store: WorkunitStore, local_parallelism: usize) -> ConsoleUI {
    ConsoleUI {
      workunit_store,
      local_parallelism,
      instance: None,
      teardown_in_progress: false,
      teardown_mpsc: mpsc::channel(),
    }
  }

  ///
  /// The number of times per-second that `Self::render` should be called.
  ///
  pub fn render_rate_hz() -> u64 {
    10
  }

  pub fn render_interval() -> Duration {
    Duration::from_millis(1000 / Self::render_rate_hz())
  }

  pub async fn with_console_ui_disabled<T>(&mut self, f: impl Future<Output = T>) -> T {
    if self.instance.is_some() {
      self.teardown().await.unwrap();
      f.await
    } else {
      f.await
    }
  }

  ///
  /// Setup progress bars, and return them along with a running task that will drive them.
  ///
  fn setup_bars(
    executor: Executor,
    num_swimlanes: usize,
  ) -> Result<(Vec<ProgressBar>, MultiProgressTask), String> {
    // Stderr is propagated across a channel to remove lock interleavings between stdio and the UI.
    let (stderr_sender, stderr_receiver) = mpsc::sync_channel(0);
    let (term_read, _, term_stderr_write) =
      stdio::get_destination().exclusive_start(Box::new(move |msg: &str| {
        // If we fail to send, it's because the UI has shut down: we fail the callback to
        // have the logging module directly log to stderr at that point.
        stderr_sender.send(msg.to_owned()).map_err(|_| ())
      }))?;

    let term = console::Term::read_write_pair(term_read, term_stderr_write);
    // NB: We render more frequently than we receive new data in order to minimize aliasing where a
    // render might barely miss a data refresh.
    let draw_target = ProgressDrawTarget::to_term(term, Self::render_rate_hz() * 2);
    let multi_progress = MultiProgress::with_draw_target(draw_target);

    let bars = (0..num_swimlanes)
      .map(|_n| {
        let style = ProgressStyle::default_bar().template("{spinner} {wide_msg}");
        multi_progress.add(ProgressBar::new(50).with_style(style))
      })
      .collect::<Vec<_>>();
    let first_bar = bars[0].downgrade();

    // Spawn a task to drive the multi progress.
    let multi_progress_task = executor
      .spawn_blocking(move || multi_progress.join())
      .boxed();
    // And another to propagate stderr, which will exit automatically when the channel closes.
    let _stderr_task = executor.spawn_blocking(move || {
      while let Ok(stderr) = stderr_receiver.recv() {
        match first_bar.upgrade() {
          Some(first_bar) => first_bar.println(stderr),
          None => break,
        }
      }
    });

    Ok((bars, multi_progress_task))
  }

  fn get_label_from_heavy_hitters<'a>(
    tasks_to_display: impl Iterator<Item = (&'a String, &'a Option<Duration>)>,
  ) -> Vec<String> {
    tasks_to_display
      .map(|(label, maybe_duration)| {
        let duration_label = match maybe_duration {
          None => "(Waiting) ".to_string(),
          Some(duration) => format_workunit_duration(*duration),
        };
        format!("{}{}", duration_label, label)
      })
      .collect()
  }

  ///
  /// Updates all of the swimlane ProgressBars with new data from the WorkunitStore. For this
  /// method to have any effect, the `initialize` method must have been called first.
  ///
  /// *Technically this method does not do the "render"ing: rather, the `MultiProgress` instance
  /// running on a background thread is drives rendering, while this method feeds it new data.
  ///
  pub fn render(&mut self) {
    let instance = if let Some(i) = &mut self.instance {
      i
    } else {
      return;
    };

    let num_swimlanes = instance.bars.len();
    let heavy_hitters = self.workunit_store.heavy_hitters(num_swimlanes);
    let tasks_to_display = &mut instance.tasks_to_display;

    // Insert every one in the set of tasks to display.
    // For tasks already here, the durations are overwritten.
    tasks_to_display.extend(heavy_hitters.clone().into_iter());

    // And remove the tasks that no longer should be there.
    for (task, _) in tasks_to_display.clone().into_iter() {
      if !heavy_hitters.contains_key(&task) {
        tasks_to_display.swap_remove(&task);
      }
    }

    let swimlane_labels: Vec<String> = Self::get_label_from_heavy_hitters(tasks_to_display.iter());
    for (n, pbar) in instance.bars.iter().enumerate() {
      match swimlane_labels.get(n) {
        Some(label) => pbar.set_message(label),
        None => pbar.set_message(""),
      }
    }
  }

  ///
  /// If the ConsoleUI is not already running, starts it.
  ///
  /// Errors if a ConsoleUI is already running (which would likely indicate concurrent usage of a
  /// Session attached to a console).
  ///
  pub fn initialize(&mut self, executor: Executor) -> Result<(), String> {
    if self.instance.is_some() {
      return Err("A ConsoleUI cannot render multiple UIs concurrently.".to_string());
    }

    // Setup bars (which will take ownership of the current Console), and then spawn rendering
    // of the bars into a background task.
    let (bars, multi_progress_task) = Self::setup_bars(executor, self.local_parallelism)?;

    self.instance = Some(Instance {
      tasks_to_display: IndexMap::new(),
      multi_progress_task,
      bars,
    });
    Ok(())
  }

  ///
  /// If the ConsoleUI is running, completes it.
  ///
  pub fn teardown(&mut self) -> impl Future<Output = Result<(), String>> {
    if let Some(instance) = self.instance.take() {
      let sender = self.teardown_mpsc.0.clone();
      self.teardown_in_progress = true;
      // When the MultiProgress completes, the Term(Destination) is dropped, which will restore
      // direct access to the Console.
      instance
        .multi_progress_task
        .map_err(|e| format!("Failed to render UI: {}", e))
        .and_then(move |()| {
          sender.send(()).unwrap();
          future::ok(())
        })
        .boxed()
    } else {
      future::ok(()).boxed()
    }
  }
}

type MultiProgressTask = Pin<Box<dyn Future<Output = std::io::Result<()>> + Send>>;

/// The state for one run of the ConsoleUI.
struct Instance {
  tasks_to_display: IndexMap<String, Option<Duration>>,
  multi_progress_task: MultiProgressTask,
  bars: Vec<ProgressBar>,
}
