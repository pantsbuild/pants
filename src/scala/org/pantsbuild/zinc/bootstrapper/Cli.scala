/**
 * Copyright (C) 2018 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.bootstrapper

import java.io.File

case class Configuration(
  outputPath: File = new File("."),
  compilerInterface: File = new File("."),
  compilerBridgeSource: File = new File("."),
  scalaCompiler: File = new File("."),
  scalaLibrary: File = new File("."),
  scalaReflect: File = new File(".")
)

object Cli {
  val CliParser = new scopt.OptionParser[Configuration]("scopt") {
    head("zinc-bootstrapper", "0.0.1")

    opt[File]('o', "out")
      .required()
      .valueName("<file>")
      .action((x, c) => c.copy(outputPath = x))
      .text("Output path for the compiler-bridge jar.")

    opt[File]("compiler-interface")
      .required()
      .valueName("<file>")
      .action((x, c) => c.copy(compilerInterface = x))
      .validate { file =>
        if (file.exists) success else failure(s"$file does not exist.")
      }
      .text("Compiler interface jar.")

    opt[File]("compiler-bridge-src")
      .required()
      .valueName("<file>")
      .action((x, c) => c.copy(compilerBridgeSource = x))
      .validate { file =>
        if (file.exists) success else failure(s"$file does not exist.")
      }
      .text("Compiler bridge source code.")

    opt[File]("scala-compiler")
      .required()
      .valueName("<file>")
      .action((x, c) => c.copy(scalaCompiler = x))
      .validate { file =>
        if (file.exists) success else failure(s"$file does not exist.")
      }
      .text("Path to the scala compiler.")

    opt[File]("scala-library")
      .required()
      .valueName("<file>")
      .action((x, c) => c.copy(scalaLibrary = x))
      .validate { file =>
        if (file.exists) success else failure(s"$file does not exist.")
      }
      .text("Path to the scala runtime library.")

    opt[File]("scala-reflect")
      .required()
      .valueName("<file>")
      .action((x, c) => c.copy(scalaReflect = x))
      .validate { file =>
        if (file.exists) success else failure(s"$file does not exist.")
      }
      .text("Path to the scala reflection library.")
  }
}
