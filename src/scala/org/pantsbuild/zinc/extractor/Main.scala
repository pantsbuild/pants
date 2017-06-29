/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.extractor

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
  }
}
