/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.File
import java.nio.file.Paths
import scala.collection.JavaConverters._

import sbt.internal.inc.IncrementalCompilerImpl
import sbt.internal.util.{ ConsoleLogger, ConsoleOut }
import sbt.io.IO
import sbt.util.Level
import xsbti.CompileFailed

import com.martiansoftware.nailgun.NGContext
import com.google.common.base.Charsets
import com.google.common.io.Files

import org.pantsbuild.zinc.analysis.AnalysisMap
import org.pantsbuild.zinc.util.Util

/**
 * Command-line main class.
 */
object Main {
  /**
   * Full zinc version info.
   */
  case class Version(published: String, timestamp: String, commit: String)

  /**
   * Get the zinc version from a generated properties file.
   */
  lazy val zincVersion: Version = {
    val props = Util.propertiesFromResource("zinc.version.properties", getClass.getClassLoader)
    Version(
      props.getProperty("version", "unknown"),
      props.getProperty("timestamp", ""),
      props.getProperty("commit", "")
    )
  }

  /**
   * For snapshots the zinc version includes timestamp and commit.
   */
  lazy val versionString: String = {
    import zincVersion._
    if (published.endsWith("-SNAPSHOT")) "%s %s-%s" format (published, timestamp, commit take 10)
    else published
  }

  def mkLogger(settings: Settings): ConsoleLogger = {
    // If someone has not explicitly enabled log4j2 JMX, disable it.
    if (!Util.isSetProperty("log4j2.disable.jmx")) {
      Util.setProperty("log4j2.disable.jmx", "true")
    }

    // As per https://github.com/pantsbuild/pants/issues/6160, this is a workaround
    // so we can run zinc without $PATH (as needed in remoting).
    System.setProperty("sbt.log.format", "true")

    val cl =
      ConsoleLogger(
        out = ConsoleOut.systemOut,
        ansiCodesSupported = settings.consoleLog.color
      )
    cl.setLevel(settings.consoleLog.logLevel)
    cl
  }

  def preprocessArgs(rawArgs: Array[String]): Array[String] = {
    val (argFiles, partialArgs) = rawArgs.partition(_.startsWith("@"))
    val args = partialArgs ++ argFiles.flatMap { f =>
      Files.readLines(new File(f.drop(1)), Charsets.UTF_8).asScala
    }
    val fixedArgs = args.flatMap { arg =>
      arg match {
        case x if x.startsWith("-C") || x.startsWith("-S") => {
          val tup = arg.splitAt(2)
          Seq(tup._1, tup._2)
        }
        case arg => Seq(arg)
      }
    }
    for (i <- 1 to fixedArgs.size) {
      // Because we set -cp as the shorthand for classpath, we can't also set -classpath as one.
      // Fix it up.
      if (fixedArgs(i - 1) == "-classpath") {
        fixedArgs(i - 1) = "--classpath"
      }
      // Old versions of this binary used :s not ,s as list separators.
      // Accept their input.
      if (fixedArgs(i - 1) == "--classpath" || fixedArgs(i - 1) == "-cp"
        || fixedArgs(i - 1) == "--scala-path" || fixedArgs(i - 1) == "-scala-path") {
        fixedArgs(i) = fixedArgs(i).replace(":", ",")
      }
      // Old versions of this binary used :s not =s as map separators.
      // Accept their input.
      if (fixedArgs(i - 1) == "--analysis-map" || fixedArgs(i - 1) == "-analysis-map") {
        fixedArgs(i) = fixedArgs(i).replace(":", "=")
      }
    }
    fixedArgs
  }

  /**
   * Run a compile.
   */
  def main(args: Array[String]): Unit = {
    val startTime = System.currentTimeMillis

    val settings = Settings.SettingsParser.parse(preprocessArgs(args), Settings()) match {
      case Some(settings) => settings
      case None => {
        println("See zinc-compiler --help for information about options")
        sys.exit(1)
      }
    }

    mainImpl(settings.withAbsolutePaths(Paths.get(".").toAbsolutePath.toFile), startTime)
  }

  def nailMain(context: NGContext): Unit = {
    val startTime = System.currentTimeMillis

    val settings = Settings.SettingsParser.parse(preprocessArgs(context.getArgs), Settings()) match {
      case Some(settings) => settings
      case None => {
        println("See zinc-compiler --help for information about options")
        sys.exit(1)
      }
    }

    mainImpl(settings.withAbsolutePaths(new File(context.getWorkingDirectory)), startTime)
  }

  def mainImpl(settings: Settings, startTime: Long): Unit = {
    val log = mkLogger(settings)

    val isDebug = settings.consoleLog.logLevel <= Level.Debug

    // if there are no sources provided, print outputs based on current analysis if requested,
    // else print version and usage by default
    if (settings.sources.isEmpty) {
      sys.exit(1)
    }

    // Load the existing analysis for the destination, if any.
    val analysisMap = AnalysisMap.create(settings.analysis)
    val (targetAnalysisStore, previousResult) =
      InputUtils.loadDestinationAnalysis(settings, analysisMap, log)
    val inputs = InputUtils.create(settings, analysisMap, previousResult, log)

    if (isDebug) {
      log.debug(s"Inputs: $inputs")
    }

    try {
      // Run the compile.
      val result = new IncrementalCompilerImpl().compile(inputs, log)

      // post compile merge dir
      if (settings.postCompileMergeDir.isDefined) {
        IO.copyDirectory(new File(settings.postCompileMergeDir.get.toURI), new File(settings.classesDirectory.toURI))
      }

      // Store the output if the result changed.
      if (result.hasModified) {
        targetAnalysisStore.set(
          // TODO
          sbt.internal.inc.ConcreteAnalysisContents(result.analysis, result.setup)
        )
      }

      log.info("Compile success " + Util.timing(startTime))

      // if compile is successful, jar the contents of classesDirectory and copy to outputJar
      if (settings.outputJar.isDefined) {
        val outputJarPath = settings.outputJar.get.toPath
        val classesDirectory = settings.classesDirectory
        log.debug("Creating JAR at %s, for files at %s" format (outputJarPath, classesDirectory))
        OutputUtils.createClassesJar(classesDirectory, outputJarPath, settings.creationTime)
      }
    } catch {
      case e: CompileFailed =>
        log.error("Compile failed " + Util.timing(startTime))
        sys.exit(1)
      case e: Exception =>
        if (isDebug) e.printStackTrace
        val message = e.getMessage
        if (message ne null) log.error(message)
        sys.exit(1)
    }
  }
}
