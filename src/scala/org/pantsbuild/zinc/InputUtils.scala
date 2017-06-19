/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.{File, IOException}
import java.util.{ List => JList, Map => JMap }

import scala.collection.JavaConverters._

import sbt.util.Logger
import xsbti.{F1, Position}
import xsbti.compile.{
  CompileOrder,
  CompileOptions,
  Compilers,
  Inputs,
  PreviousResult
}

object InputUtils {
  /**
   * Create Inputs based on command-line settings.
   */
  def create(log: Logger, settings: Settings, previousResult: PreviousResult): Inputs = {
    import settings._

    // TODO: unused?
    val progress =
      new SimpleCompileProgress(
        consoleLog.logPhases,
        consoleLog.printProgress,
        consoleLog.heartbeatSecs
      )(log)

    val analysisMap = AnalysisMap.create(cacheMap, log)

    val setup = Setup(settings)
    val compilers = CompilerUtils.getOrCreate(setup, log)

    val compileOptions =
      new CompileOptions(
        autoClasspath(
          classesDirectory,
          compilers.scalac().scalaInstance().allJars,
          javaOnly,
          classpath
        ).toArray,
        sources.toArray,
        classesDirectory,
        scalacOptions.toArray,
        javacOptions.toArray,
        Int.MaxValue,
        // Noop `sourcePositionMapper`.
        new F1[Position, Position] {
          override def apply(p: Position): Position = p
        },
        compileOrder
      )

    new Inputs(
      compilers,
      compileOptions,
      setup,
      previousResult
    )
  }

  /**
   * Automatically add the output directory and scala library to the classpath.
   */
  def autoClasspath(classesDirectory: File, allScalaJars: Seq[File], javaOnly: Boolean, classpath: Seq[File]): Seq[File] = {
    if (javaOnly) classesDirectory +: classpath
    else Setup.splitScala(allScalaJars) match {
      case Some(scalaJars) => classesDirectory +: scalaJars.library +: classpath
      case None            => classesDirectory +: classpath
    }
  }
}
