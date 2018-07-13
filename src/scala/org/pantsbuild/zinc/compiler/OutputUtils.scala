/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.File
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.{FileVisitResult, Files, Path, Paths, SimpleFileVisitor}
import java.util.function.{Function => JFunction}
import java.util.jar.{JarEntry, JarOutputStream}
import org.pantsbuild.zinc.analysis.AnalysisMap

import scala.collection.JavaConverters._
import scala.compat.java8.OptionConverters._
import scala.util.matching.Regex

import sbt.io.IO
import sbt.util.Logger
import xsbti.{Position, Problem, Severity, ReporterConfig, ReporterUtil}
import xsbti.compile.{
  AnalysisStore,
  CompileOptions,
  CompileOrder,
  Compilers,
  Inputs,
  PreviousResult,
  Setup
}

object OutputUtils {

  /**
   * Jar the contents of output classes (settings.classesDirectory) and copy to settings.outputJar
   */
  def createClassesJar(settings: Settings, log: Logger) = {
    val classesDirectory = settings.classesDirectory
    val jarCaptureVisitor = new SimpleFileVisitor[Path]() {
      def done(): Path = {
        target.close()
        log.debug("Output jar generated at: " + jarPath)
        // TODO(ity): Delete the temp classesDirectory, if one was created
        jarPath
      }

      val jarPath = Paths.get(classesDirectory.toString, settings.outputJar.toString)
      val target = new JarOutputStream(Files.newOutputStream(jarPath))

      override def visitFile(source: Path, attrs: BasicFileAttributes): FileVisitResult = {
        val jarEntry = new JarEntry(source.toString)
        // setting jarEntry time to a fixed value for all entries within the jar for determinism
        // and so that jarfiles are byte-for-byte reproducible.
        jarEntry.setTime(settings.creationTime)

        log.debug("Creating jar entry " + jarEntry + " for the file " + source)

        target.putNextEntry(jarEntry)
        Files.copy(source, target)
        target.closeEntry()
        FileVisitResult.CONTINUE
      }

    }
    Files.walkFileTree(classesDirectory.toPath, jarCaptureVisitor)
    jarCaptureVisitor.done()
  }
}
