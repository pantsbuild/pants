// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cmp;
use std::collections::HashMap;
use std::future;
use std::sync::Arc;
use std::time::SystemTime;

use futures::future::BoxFuture;
use futures::FutureExt;
use indexmap::IndexSet;
use indicatif::MultiProgress;
use indicatif::ProgressBar;
use indicatif::ProgressDrawTarget;
use indicatif::ProgressStyle;
use indicatif::WeakProgressBar;
use parking_lot::Mutex;

use workunit_store::format_workunit_duration_ms;
use workunit_store::SpanId;

use super::TaskState;
use crate::ConsoleUI;
use crate::LogStreamingLines;
use crate::LogStreamingTopn;

const RESERVED_OUTPUT_LOG_LINES: usize = 10;
pub struct IndicatifInstance {
    tasks_to_display: IndexSet<SpanId>,
    // NB: Kept for Drop.
    _multi_progress: MultiProgress,
    bars: Vec<ProgressBar>,

    terminal_width: u16,
    log_streaming: bool,
    log_streaming_lines: usize,
    log_streaming_topn: usize,
}

impl IndicatifInstance {
    pub fn new(
        local_parallelism: usize,
        terminal_width: u16,
        terminal_height: u16,

        log_streaming: bool,
        log_streaming_lines: LogStreamingLines,
        log_streaming_topn: LogStreamingTopn,
    ) -> Result<IndicatifInstance, String> {
        // We take exclusive access to stdio by registering a callback that is used to render stderr
        // while we're holding access. See the method doc.
        // TODO: `MultiProgress` now supports `println` directly. However, it doesn't support
        // `downgrade`.
        let stderr_dest_bar: Arc<Mutex<Option<WeakProgressBar>>> = Arc::new(Mutex::new(None));

        // We acquire the lock before taking exclusive access, and don't release it until after
        // initialization. That way, the exclusive callback can always assume that the destination
        // is initialized (i.e., can `unwrap` it).
        let mut stderr_dest_bar_guard = stderr_dest_bar.lock();
        let multi_progress = setup_bar_outputs(stderr_dest_bar.clone())?;

        let bars = (0..cmp::min(local_parallelism, terminal_height.into()))
            .map(|_n| {
                let style = ProgressStyle::default_bar()
                    .template("{spinner} {prefix}{msg}")
                    .expect("Valid template.");

                multi_progress.add(ProgressBar::new(terminal_width.into()).with_style(style))
            })
            .collect::<Vec<_>>();

        *stderr_dest_bar_guard = Some(bars[0].downgrade());

        let (log_lines, log_topn) = log_streaming_sizes(
            terminal_height,
            &bars,
            log_streaming,
            log_streaming_lines,
            log_streaming_topn,
        );

        eprintln!(
                "log_streaming: {}, log_lines: {}, log_topn: {}, log_streaming_lines: {:?}, log_streaming_topn: {:?}
",
                log_streaming, log_lines, log_topn, log_streaming_lines, log_streaming_topn
            );

        Ok(IndicatifInstance {
            tasks_to_display: IndexSet::new(),
            _multi_progress: multi_progress,
            bars,
            terminal_width,

            log_streaming,
            log_streaming_lines: log_lines,
            log_streaming_topn: log_topn,
        })
    }

    pub fn teardown(self) -> BoxFuture<'static, ()> {
        // When the MultiProgress completes, the Term(Destination) is dropped, which will restore
        // direct access to the Console.
        std::mem::drop(self);
        future::ready(()).boxed()
    }

    pub fn render(
        &mut self,
        heavy_hitters: &HashMap<SpanId, (String, SystemTime)>,
        log_retriever: &mut dyn FnMut(SpanId, usize) -> Option<Vec<u8>>,
    ) {
        let tasks_to_display = &mut self.tasks_to_display;
        super::classify_tasks(
            heavy_hitters,
            tasks_to_display.iter().cloned().collect(),
            &mut |span_id, task_state| match task_state {
                TaskState::Remove => {
                    tasks_to_display.swap_remove(&span_id);
                }
                TaskState::Update => {
                    tasks_to_display.insert(span_id);
                }
                TaskState::New => {
                    tasks_to_display.insert(span_id);
                }
            },
        );

        let now = SystemTime::now();
        for (n, pbar) in self.bars.iter().enumerate() {
            let maybe_label = tasks_to_display.get_index(n).and_then(|span_id| {
                let log_lines = (self.log_streaming && n <= self.log_streaming_topn)
                    .then(|| log_retriever(*span_id, self.log_streaming_lines))
                    .flatten();

                let (label, start_time) = heavy_hitters.get(span_id).unwrap();
                let duration_label = match now.duration_since(*start_time).ok() {
                    None => "(Waiting)".to_string(),
                    Some(duration) => {
                        format_workunit_duration_ms!((duration).as_millis()).to_string()
                    }
                };

                // we remove the duration spinner, space, duration label, space
                let max_label_len =
                    (self.terminal_width as usize).saturating_sub(duration_label.len() + 3);
                let label = if log_lines.as_ref().map_or(false, |lines| !lines.is_empty()) {
                    format!("{duration_label} {label:.*}\n", max_label_len)
                } else {
                    format!("{duration_label} {label:.*}", max_label_len)
                };

                Some((label, log_lines))
            });

            match maybe_label {
                Some((label, maybe_message)) => {
                    pbar.set_prefix(label);

                    match maybe_message {
                        Some(message) if !message.is_empty() => {
                            let message: String =
                                String::from_utf8_lossy(message.as_slice()).into();
                            pbar.set_message(message);
                        }
                        _ => pbar.set_message(""),
                    }
                }
                None => {
                    pbar.set_prefix("");
                    pbar.set_message("");
                }
            }

            pbar.tick();
        }
    }
}

fn log_streaming_sizes(
    terminal_height: u16,
    bars: &Vec<ProgressBar>,
    log_streaming: bool,
    log_streaming_lines: LogStreamingLines,
    log_streaming_topn: LogStreamingTopn,
) -> (usize, usize) {
    let th = terminal_height as usize;
    let remaining = th
        .saturating_sub(RESERVED_OUTPUT_LOG_LINES)
        .saturating_sub(bars.len());

    let (log_streaming_lines, log_streaming_topn) = if log_streaming {
        match (log_streaming_lines, log_streaming_topn) {
            (LogStreamingLines::Exact(l), LogStreamingTopn::Exact(t)) => (l, t),
            (LogStreamingLines::Exact(l), LogStreamingTopn::Auto) => {
                let remaining = th
                    .saturating_sub(RESERVED_OUTPUT_LOG_LINES)
                    .saturating_sub(bars.len());

                // +1 for header
                let topn = remaining / l;
                (l, topn)
            }
            (LogStreamingLines::Auto, LogStreamingTopn::Exact(t)) => {
                let lines = remaining / t;
                (lines, t)
            }
            (LogStreamingLines::Auto, LogStreamingTopn::Auto) => {
                let remaining = th
                    .saturating_sub(RESERVED_OUTPUT_LOG_LINES)
                    .saturating_sub(bars.len());

                let target_topn = bars.len() / 2;
                let target_lines = remaining / target_topn;

                (target_lines, target_topn)
            }
        }
    } else {
        (0, 0)
    };
    (log_streaming_lines, log_streaming_topn)
}

fn setup_bar_outputs(
    stderr_dest_bar: Arc<Mutex<Option<WeakProgressBar>>>,
) -> Result<MultiProgress, String> {
    let (term_read, _, term_stderr_write) = {
        let stderr_dest_bar = stderr_dest_bar.clone();
        stdio::get_destination().exclusive_start(Box::new(move |msg: &str| {
            // Acquire a handle to the destination bar in the UI. If we fail to upgrade, it's because
            // the UI has shut down: we fail the callback to have the logging module directly log to
            // stderr at that point.
            let dest_bar = {
                let stderr_dest_bar = stderr_dest_bar.lock();
                // We can safely unwrap here because the Mutex is held until the bar is initialized.
                stderr_dest_bar.as_ref().unwrap().upgrade().ok_or(())?
            };
            dest_bar.println(msg);
            Ok(())
        }))?
    };
    let stderr_use_color = term_stderr_write.use_color;
    let term = console::Term::read_write_pair_with_style(
        term_read,
        term_stderr_write,
        console::Style::new().force_styling(stderr_use_color),
    );
    let draw_target = ProgressDrawTarget::term(term, ConsoleUI::render_rate_hz() * 2);
    let multi_progress = MultiProgress::with_draw_target(draw_target);
    Ok(multi_progress)
}
