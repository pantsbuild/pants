package org.pantsbuild.zinc

import xsbti.compile.CompileProgress
import sbt.Logger

/**
 * SimpleCompileProgress implements CompileProgress to add output to zinc scala compilations, but
 * does not implement the capability to cancel compilations via the `advance` method.
 */
class SimpleCompileProgress(logPhases: Boolean, printProgress: Boolean, heartbeatSecs: Int)(log: LoggerRaw) extends CompileProgress {
  @volatile private var lastHeartbeatMillis: Long = 0

  /**
   * startUnit Optionally reports to stdout when a phase of compilation has begun for a file.
   */
  def startUnit(phase: String, unitPath: String): Unit =  {
    if (logPhases) {
      log.info(phase + " " + unitPath + "...")
    }
  }

  /**
   * advance Optionally emit the percentage of steps completed, and/or a heartbeat ('.' character)
   * roughly every `heartbeatSecs` seconds. If `heartbeatSecs` is not greater than 0, no heartbeat
   * is emitted.
   *
   * advance is periodically called during compilation, indicating the total number of compilation
   * steps completed (`current`) out of the total number of steps necessary. The method returns
   * false if the user wishes to cancel compilation, or true otherwise. Currently, Zinc never
   * requests to cancel compilation.
   */
  def advance(current: Int, total: Int): Boolean = {
    if (printProgress) {
      val percent = (current * 100) / total
      log.logRaw(s"\rProgress: ${percent}%")
    }
    if (heartbeatSecs > 0) {
      val currentTimeMillis = System.currentTimeMillis
      val delta = currentTimeMillis - lastHeartbeatMillis
      if (delta > (1000 * heartbeatSecs)) {
        log.logRaw(".")
        lastHeartbeatMillis = currentTimeMillis
      }
    }
    /* Always continue compiling. */
    true
  }
}
