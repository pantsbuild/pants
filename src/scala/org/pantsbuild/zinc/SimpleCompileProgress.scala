package com.typesafe.zinc

import xsbti.compile.CompileProgress
import sbt.Logger

/**
 * SimpleCompileProgress implements CompileProgress to add output to zinc scala compilations, but
 * does not implement the capability to cancel compilations via the `advance` method.
 */
class SimpleCompileProgress (logPhases: Boolean, logProgress: Boolean)(log: Logger) extends CompileProgress {
  @volatile private var lastStep: Int = 0

  /** 
   * startUnit Optionally reports to stdout when a phase of compilation has begun for a file.
   */
  def startUnit(phase: String, unitPath: String): Unit =  {
    if (logPhases) {
      log.info(phase + " " + unitPath + "...")
    }
  }

  /**
   * advance Optionally reports the number of compilation units completed out of the total.
   * 
   * advance is periodically called during compilation, indicating the total number of compilation 
   * steps completed (`current`) out of the total number of steps necessary. The method returns 
   * false if the user wishes to cancel compilation, or true otherwise. Currently, Zinc never 
   * requests to cancel compilation.
   */
  def advance(current: Int, total: Int): Boolean = {
    if (logProgress) {
      if (current > lastStep) {
        log.info("Progress: [" + current + "/" + total + "]")
        lastStep = current
      }
    }
    true
  }
}
