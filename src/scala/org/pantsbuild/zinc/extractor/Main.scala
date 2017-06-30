/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.extractor

import sbt.internal.inc.FileBasedStore

import org.pantsbuild.zinc.analysis.PortableAnalysisMappers
import org.pantsbuild.zinc.options.Parsed

/**
 * Command-line main class for analysis extraction.
 */
object Main {
  val Command = "zinc-extractor"

  def main(args: Array[String]): Unit = {
    val Parsed(settings, residual, errors) = Settings.parse(args)

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) System.err.println(error)
      System.err.println("See %s -help for information about options" format Command)
      sys.exit(1)
    }

    if (settings.help) Settings.printUsage(Command)

    val analysis =
      FileBasedStore(
        settings.analysis.cache,
        new PortableAnalysisMappers(settings.analysis.rebaseMap)
      )
        .get()
        .getOrElse {
          throw new RuntimeException(s"Failed to load analysis from ${settings.analysis.cache}")
        }
        ._1

    println(analysis)
  }
}
