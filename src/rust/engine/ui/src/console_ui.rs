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
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::collections::HashMap;
use std::fmt;
use std::future::Future;
use std::sync::mpsc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use prodash::progress::Step;
use prodash::render::line;
use prodash::{Root, TreeOptions};
use task_executor::Executor;
use workunit_store::{format_workunit_duration_ms, SpanId, WorkunitStore};

pub struct ConsoleUI {
  workunit_store: WorkunitStore,
  local_parallelism: usize,
  // While the UI is running, there will be an Instance present.
  instance: Option<Instance>,
}

impl ConsoleUI {
  pub fn new(workunit_store: WorkunitStore, local_parallelism: usize) -> ConsoleUI {
    ConsoleUI {
      workunit_store,
      local_parallelism,
      instance: None,
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
      self.teardown().await;
      f.await
    } else {
      f.await
    }
  }

  ///
  /// Setup an Instance of the UI renderer.
  ///
  /// NB: This method must be very careful to avoid logging. Between the point where we have taken
  /// exclusive access to the Console and when the UI has actually been initialized, attempts to
  /// log from this method would deadlock (by causing the method to wait for _itself_ to finish).
  ///
  fn setup_renderer(&self, executor: Executor) -> Result<Instance, String> {
    // Stderr is propagated across a channel to remove lock interleavings between stdio and the UI.
    // TODO: Apply a fix similar to #14093 before landing.
    let (stderr_sender, stderr_receiver) = mpsc::sync_channel(0);
    let (_term_read, _term_stdout_write, term_stderr_write) = stdio::get_destination()
      .exclusive_start(Box::new(move |msg: &str| {
        // If we fail to send, it's because the UI has shut down: we fail the callback to
        // have the logging module directly log to stderr at that point.
        stderr_sender.send(msg.to_owned()).map_err(|_| ())
      }))?;

    let colored = term_stderr_write.use_color;
    let tree = TreeOptions {
      initial_capacity: 1024,
      // This is the capacity in terms of lines that will be buffered between frames: writing more
      // than this amount per frame will drop some on the floor.
      message_buffer_capacity: 65536,
    }
    .create();
    // NB: We render more frequently than we receive new data in order to minimize aliasing where a
    // render might barely miss a data refresh.
    let handle = line::render(
      term_stderr_write,
      tree.clone(),
      line::Options {
        colored,
        // This is confirmed before creating a UI.
        output_is_terminal: true,
        hide_cursor: true,
        // TODO: Adjust this.
        frames_per_second: Self::render_rate_hz() as f32,
        // TODO: We only render items with duration, so is probably currently a noop. But in
        // the future, we would want to render progress.
        throughput: true,
        // TODO: Set this.
        // terminal_dimensions,
        ..Default::default()
      },
    );

    // Spawn a task to propagate stderr, which will exit automatically when the channel closes.
    // TODO: There is a shutdown race here, where if the UI is torn down before exclusive access is
    // dropped, we might drop stderr on the floor. That likely causes:
    //   https://github.com/pantsbuild/pants/issues/13276
    let _stderr_task = executor.spawn_blocking({
      let mut tree = tree.clone();
      move || {
        while let Ok(stderr) = stderr_receiver.recv() {
          tree.message_raw(stderr);
        }
      }
    });

    Ok(Instance {
      tasks_to_display: HashMap::new(),
      tree,
      handle,
      executor,
    })
  }

  ///
  /// Updates all of prodash items with new data from the WorkunitStore. For this
  /// method to have any effect, the `initialize` method must have been called first.
  ///
  /// *Technically this method does not do the "render"ing: rather, the background prodash task
  /// drives rendering, while this method feeds it new data.
  ///
  pub fn render(&mut self) {
    let instance = if let Some(i) = &mut self.instance {
      i
    } else {
      return;
    };

    let heavy_hitters = self.workunit_store.heavy_hitters(self.local_parallelism);
    let tasks_to_display = &mut instance.tasks_to_display;

    // Finish any items that are no longer relevant.
    for span_id in tasks_to_display.keys().cloned().collect::<Vec<_>>() {
      if heavy_hitters.contains_key(&span_id) {
        continue;
      }
      // Drop the item to cause it to be removed from the Tree.
      let _ = tasks_to_display.remove(&span_id).unwrap();
    }

    // Start any new items.
    let now = SystemTime::now();
    for (span_id, (description, duration)) in heavy_hitters {
      if tasks_to_display.contains_key(&span_id) {
        // We're already rendering this item, and our dynamic `unit` instance will continue to
        // handle rendering elapsed time for it.
        continue;
      }

      // Else, it's new.
      // TODO: This should be based dynamically on the current width of the terminal.
      let max_len = 100;
      let description: String = if description.len() < max_len {
        description
      } else {
        description
          .chars()
          .take(max_len - 3)
          .chain(std::iter::repeat('.').take(3))
          .collect()
      };
      let mut item = instance.tree.add_child(description);
      item.init(
        None,
        Some(prodash::unit::dynamic(MillisAsFloatingPointSecs)),
      );
      item.set(MillisAsFloatingPointSecs::duration_to_step(&now, duration));
      tasks_to_display.insert(span_id, item);
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

    self.instance = Some(self.setup_renderer(executor)?);

    Ok(())
  }

  ///
  /// If the ConsoleUI is running, completes it.
  ///
  pub async fn teardown(&mut self) {
    if let Some(instance) = self.instance.take() {
      instance
        .executor
        .clone()
        .spawn_blocking(move || {
          // TODO: Necessary to do this on Drop as well? Or do we guarantee that teardown is called?
          instance.handle.shutdown_and_wait();
        })
        .await
    }
  }
}

/// The state for one run of the ConsoleUI.
struct Instance {
  tasks_to_display: HashMap<SpanId, prodash::tree::Item>,
  tree: prodash::Tree,
  handle: line::JoinHandle,
  executor: Executor,
}

/// Renders a millis-since-epoch unit as floating point seconds.
#[derive(Copy, Clone, Default, Eq, PartialEq, Ord, PartialOrd, Debug)]
struct MillisAsFloatingPointSecs;

impl MillisAsFloatingPointSecs {
  /// Computes a static Step value from the given Duration by converting it to "millis-since-epoch".
  fn duration_to_step(now: &SystemTime, duration: Option<Duration>) -> Step {
    // TODO: Use workunit start SystemTimes directly rather than calculating them.
    let start_time = duration.and_then(|d| now.checked_sub(d)).unwrap_or(*now);
    start_time.duration_since(UNIX_EPOCH).unwrap().as_millis() as usize
  }
}

impl prodash::unit::DisplayValue for MillisAsFloatingPointSecs {
  fn display_current_value(
    &self,
    w: &mut dyn fmt::Write,
    value: Step,
    _upper: Option<Step>,
  ) -> fmt::Result {
    // Convert back from millis-since-epoch to millis elapsed.
    let start_time = UNIX_EPOCH + Duration::from_millis(value as u64);
    let elapsed_ms = start_time.elapsed().map(|d| d.as_millis()).unwrap_or(0);
    w.write_fmt(format_workunit_duration_ms!(elapsed_ms))
  }
  fn display_unit(&self, _w: &mut dyn fmt::Write, _value: Step) -> fmt::Result {
    Ok(())
  }
}
