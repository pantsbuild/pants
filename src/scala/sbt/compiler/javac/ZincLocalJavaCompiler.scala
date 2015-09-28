/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package sbt.compiler.javac

import java.io.{ File, PrintWriter }

import xsbti.Reporter
import sbt.{ LoggerWriter, Logger }

/**
 * TODO: A backport of
 *   https://github.com/sbt/sbt/pull/2108
 *   https://github.com/sbt/sbt/pull/2201
 * ... which didn't make the 0.13.9 release.
 *
 * Do NOT edit without also pushing the changes upstream.
 */
@deprecated("Backport of changes that should be available in 0.13.10", "0.13.9")
final class ZincLocalJavaCompiler(compiler: javax.tools.JavaCompiler) extends JavaCompiler {
  override def run(sources: Seq[File], options: Seq[String])(implicit log: Logger, reporter: Reporter): Boolean = {
    import collection.JavaConverters._
    val logger = new LoggerWriter(log)
    val logWriter = new PrintWriter(logger)
    log.debug("Attempting to call " + compiler + " directly...")
    val diagnostics = new ZincDiagnosticsReporter(reporter)
    val fileManager = compiler.getStandardFileManager(diagnostics, null, null)
    val jfiles = fileManager.getJavaFileObjectsFromFiles(sources.asJava)
    compiler.getTask(logWriter, fileManager, diagnostics, options.asJava, null, jfiles).call()
  }
}
