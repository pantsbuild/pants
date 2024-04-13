// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::fmt;
use std::sync::mpsc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use futures::future::BoxFuture;
use futures::FutureExt;
use prodash::progress::Step;
use prodash::render::line;
use prodash::Root;
use prodash::TreeOptions;

use logging::fatal_log;
use task_executor::Executor;
use workunit_store::format_workunit_duration_ms;
use workunit_store::SpanId;

use super::TaskState;
use crate::ConsoleUI;

pub struct ProdashInstance {
    tasks_to_display: HashMap<SpanId, prodash::tree::Item>,
    tree: prodash::Tree,
    handle: line::JoinHandle,
    terminal_width: u16,
    executor: Executor,
}

impl ProdashInstance {
    pub fn new(
        executor: Executor,
        terminal_width: u16,
        terminal_height: u16,
    ) -> Result<ProdashInstance, String> {
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
                frames_per_second: ConsoleUI::render_rate_hz() as f32,
                throughput: false,
                terminal_dimensions: (terminal_width, terminal_height),
                ..prodash::render::line::Options::default()
            },
        );

        // Spawn a task to propagate stderr, which will exit automatically when the channel closes.
        // TODO: There is a shutdown race here, where if the UI is torn down before exclusive access is
        // dropped, we might drop stderr on the floor. That likely causes:
        //   https://github.com/pantsbuild/pants/issues/13276
        let _stderr_task = executor.native_spawn_blocking({
            let mut tree = tree.clone();
            move || {
                while let Ok(stderr) = stderr_receiver.recv() {
                    tree.message_raw(stderr);
                }
            }
        });

        Ok(ProdashInstance {
            tasks_to_display: HashMap::new(),
            tree,
            handle,
            terminal_width,
            executor,
        })
    }

    pub fn teardown(mut self) -> BoxFuture<'static, ()> {
        // Drop all tasks to clear the Tree. The call to shutdown will render a final "Tick" with the
        // empty Tree, which will clear the screen.
        self.tasks_to_display.clear();
        self.executor
            .clone()
            .spawn_blocking(
                move || self.handle.shutdown_and_wait(),
                |e| fatal_log!("Failed to teardown UI: {e}"),
            )
            .boxed()
    }

    pub fn render(&mut self, heavy_hitters: &HashMap<SpanId, (String, SystemTime)>) {
        let tasks_to_display = &mut self.tasks_to_display;
        super::classify_tasks(
            heavy_hitters,
            tasks_to_display.keys().cloned().collect(),
            &mut |span_id, task_state: TaskState| match task_state {
                TaskState::Remove => {
                    tasks_to_display.remove(&span_id);
                }
                TaskState::Update => {
                    // NB: `inc` moves the "worms" to help show ongoing progress.
                    tasks_to_display.get_mut(&span_id).unwrap().inc();
                }
                TaskState::New => {
                    let (desc, start_time) = heavy_hitters.get(&span_id).unwrap();
                    // NB: Allow a 8 char "buffer" to allow for timing and spaces.
                    let max_len = (self.terminal_width as usize) - 8;
                    let description: String = if desc.len() < max_len {
                        desc.to_string()
                    } else {
                        desc.chars()
                            .take(max_len - 3)
                            .chain(std::iter::repeat('.').take(3))
                            .collect()
                    };
                    let mut item = self.tree.add_child(description);
                    item.init(
                        None,
                        Some(prodash::unit::dynamic(MillisAsFloatingPointSecs)),
                    );
                    item.set(MillisAsFloatingPointSecs::start_time_to_step(start_time));
                    tasks_to_display.insert(span_id, item);
                }
            },
        )
    }
}

/// Renders a millis-since-epoch unit as floating point seconds.
#[derive(Copy, Clone, Default, Eq, PartialEq, Ord, PartialOrd, Debug)]
struct MillisAsFloatingPointSecs;

impl MillisAsFloatingPointSecs {
    /// Computes a static Step from the given start time by converting it to "millis-since-epoch".
    fn start_time_to_step(start_time: &SystemTime) -> Step {
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
