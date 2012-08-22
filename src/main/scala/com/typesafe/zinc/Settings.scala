/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.File
import sbt.Level
import sbt.Path._
import xsbti.compile.CompileOrder

/**
 * All parsed command-line options.
 */
case class Settings(
  help: Boolean = false,
  version: Boolean = false,
  quiet: Boolean = false,
  logLevel: Level.Value = Level.Info,
  color: Boolean = true,
  sources: Seq[File] = Seq.empty,
  classpath: Seq[File] = Seq.empty,
  classesDirectory: File = new File("."),
  scala: ScalaLocation = ScalaLocation(),
  scalacOptions: Seq[String] = Seq.empty,
  javaHome: Option[File] = None,
  javaOnly: Boolean = false,
  javacOptions: Seq[String] = Seq.empty,
  compileOrder: CompileOrder = CompileOrder.Mixed,
  sbt: SbtJars = SbtJars(),
  analysis: AnalysisOptions = AnalysisOptions(),
  properties: Seq[String] = Seq.empty)

/**
 * Alternative ways to locate the scala jars.
 */
case class ScalaLocation(
  home: Option[File] = None,
  path: Seq[File] = Seq.empty,
  compiler: Option[File] = None,
  library: Option[File] = None,
  extra: Seq[File] = Seq.empty)

/**
 * Locating the sbt jars needed for zinc compile.
 */
case class SbtJars(
  sbtInterface: Option[File] = None,
  compilerInterfaceSrc: Option[File] = None)

/**
 * Configuration for sbt analysis and analysis output options.
 */
case class AnalysisOptions(
  cache: Option[File] = None,
  cacheMap: Map[File, File] = Map.empty,
  outputRelations: Option[File] = None,
  outputProducts: Option[File] = None
)

object Settings {
  /**
   * All available command-line options.
   */
  val options = Seq(
    header("Output options:"),
    boolean( ("-help", "-h"),                "Print this usage message",                   (s: Settings) => s.copy(help = true)),
    boolean( "-version",                     "Print version",                              (s: Settings) => s.copy(version = true)),
    boolean( ("-quiet", "-q"),               "Silence all logging",                        (s: Settings) => s.copy(quiet = true)),
    boolean( "-debug",                       "Set log level to debug",                     (s: Settings) => s.copy(logLevel = Level.Debug)),
    string(  "-log-level", "level",          "Set log level (debug|info|warn|error)",      (s: Settings, l: String) => s.copy(logLevel = Level.withName(l))),
    boolean( "-no-color",                    "No color in logging",                        (s: Settings) => s.copy(color = false)),

    header("Compile options:"),
    path(    ("-classpath", "-cp"), "path",  "Specify the classpath",                      (s: Settings, cp: Seq[File]) => s.copy(classpath = cp)),
    file(    "-d", "directory",              "Destination for compiled classes",           (s: Settings, f: File) => s.copy(classesDirectory = f)),

    header("Scala options:"),
    file(    "-scala-home", "directory",     "Scala home directory (for locating jars)",   (s: Settings, f: File) => s.copy(scala = s.scala.copy(home = Some(f)))),
    path(    "-scala-path", "path",          "Specify all Scala jars directly",            (s: Settings, sp: Seq[File]) => s.copy(scala = s.scala.copy(path = sp))),
    file(    "-scala-compiler", "file",      "Specify Scala compiler jar directly" ,       (s: Settings, f: File) => s.copy(scala = s.scala.copy(compiler = Some(f)))),
    file(    "-scala-library", "file",       "Specify Scala library jar directly" ,        (s: Settings, f: File) => s.copy(scala = s.scala.copy(library = Some(f)))),
    path(    "-scala-extra", "path",         "Specify extra Scala jars directly",          (s: Settings, e: Seq[File]) => s.copy(scala = s.scala.copy(extra = e))),
    prefix(  "-S", "<scalac-option>",        "Pass option to scalac",                      (s: Settings, o: String) => s.copy(scalacOptions = s.scalacOptions :+ o)),

    header("Java options:"),
    file(    "-java-home", "directory",      "Java home directory (to select javac)",      (s: Settings, f: File) => s.copy(javaHome = Some(f))),
    string(  "-compile-order", "order",      "Compile order for Scala and Java sources",   (s: Settings, o: String) => s.copy(compileOrder = compileOrder(o))),
    boolean( "-java-only",                   "Don't add scala library to classpath",       (s: Settings) => s.copy(javaOnly = true)),
    prefix(  "-J", "<javac-option>",         "Pass option to javac",                       (s: Settings, o: String) => s.copy(javacOptions = s.javacOptions :+ o)),

    header("sbt options:"),
    file(    "-sbt-interface", "file",       "Specify sbt interface jar",                  (s: Settings, f: File) => s.copy(sbt = s.sbt.copy(sbtInterface = Some(f)))),
    file(    "-compiler-interface", "file",  "Specify compiler interface sources jar",     (s: Settings, f: File) => s.copy(sbt = s.sbt.copy(compilerInterfaceSrc = Some(f)))),

    header("Analysis options:"),
    file(    "-analysis-cache", "file",      "Cache file for compile analysis",            (s: Settings, f: File) => s.copy(analysis = s.analysis.copy(cache = Some(f)))),
    fileMap( "-analysis-map",                "Upstream analysis mapping (file:file,...)",  (s: Settings, m: Map[File, File]) => s.copy(analysis = s.analysis.copy(cacheMap = m))),
    file(    "-output-relations", "file",    "Print readable analysis relations to file",  (s: Settings, f: File) => s.copy(analysis = s.analysis.copy(outputRelations = Some(f)))),
    file(    "-output-products", "file",     "Print readable source products to file",     (s: Settings, f: File) => s.copy(analysis = s.analysis.copy(outputProducts = Some(f)))),

    header("JVM options:"),
    prefix(  "-D", "property=value",         "Pass property to runtime system",            (s: Settings, o: String) => s.copy(properties = s.properties :+ o)),
    dummy(   "-V<flag>",                     "Set JVM flag directly for this process"),

    header("Nailgun options:"),
    dummy(   "-nailed",                      "Run as daemon with nailgun server"),
    dummy(   "-port",                        "Set nailgun port (if nailed)"),
    dummy(   "-start",                       "Ensure nailgun server is running (if nailed)"),
    dummy(   "-status",                      "Report nailgun server status (if nailed)"),
    dummy(   "-shutdown",                    "Shutdown nailgun server (if nailed)"),
    dummy(   "-idle-timeout <duration>",     "Set idle timeout (Nh|Nm|Ns) (if nailed)")
  )

  val allOptions: Set[OptionDef[Settings]] = options.toSet

  /**
   * Print out the usage message.
   */
  def printUsage(): Unit = {
    val column = options.map(_.length).max + 2
    println("Usage: %s <options> <sources>" format Setup.Command)
    options foreach { opt => if (opt.extraline) println(); println(opt.usage(column)) }
    println()
  }

  /**
   * Anything starting with '-' is considered an option, not a source file.
   */
  def isOpt(s: String) = s startsWith "-"

  /**
   * Parse all args into a Settings object.
   * Residual args are either unknown options or source files.
   */
  def parse(args: Seq[String]): Parsed[Settings] = {
    val Parsed(settings, remaining, errors) = Options.parse(Settings(), allOptions, args, stopOnError = false)
    val (unknown, residual) = remaining partition isOpt
    val sources = residual map (new File(_))
    val unknownErrors = unknown map ("Unknown option: " + _)
    Parsed(settings.copy(sources = sources), Seq.empty, errors ++ unknownErrors)
  }

  /**
   * Create a CompileOrder value based on string input.
   */
  def compileOrder(order: String): CompileOrder = {
    order.toLowerCase match {
      case "mixed"                                       => CompileOrder.Mixed
      case "java"  | "java-then-scala" | "javathenscala" => CompileOrder.JavaThenScala
      case "scala" | "scala-then-java" | "scalathenjava" => CompileOrder.ScalaThenJava
    }
  }

  /**
   * Normalise all relative paths to the actual current working directory, if provided.
   */
  def normalise(settings: Settings, cwd: Option[File]): Settings = {
    if (cwd.isEmpty) settings
    else {
      import settings._
      settings.copy(
        sources = Util.normaliseSeq(cwd)(sources),
        classpath = Util.normaliseSeq(cwd)(classpath),
        classesDirectory = Util.normalise(cwd)(classesDirectory),
        scala = scala.copy(
          home = Util.normaliseOpt(cwd)(scala.home),
          path = Util.normaliseSeq(cwd)(scala.path),
          compiler = Util.normaliseOpt(cwd)(scala.compiler),
          library = Util.normaliseOpt(cwd)(scala.library),
          extra = Util.normaliseSeq(cwd)(scala.extra)
        ),
        javaHome = Util.normaliseOpt(cwd)(javaHome),
        sbt = sbt.copy(
          sbtInterface = Util.normaliseOpt(cwd)(sbt.sbtInterface),
          compilerInterfaceSrc = Util.normaliseOpt(cwd)(sbt.compilerInterfaceSrc)
        ),
        analysis = analysis.copy(
          cache = Util.normaliseOpt(cwd)(analysis.cache),
          cacheMap = Util.normaliseMap(cwd)(analysis.cacheMap),
          outputRelations = Util.normaliseOpt(cwd)(analysis.outputRelations),
          outputProducts = Util.normaliseOpt(cwd)(analysis.outputProducts)
        )
      )
    }
  }

  // helpers for creating options

  def boolean(opt: String, desc: String, action: Settings => Settings) = new BooleanOption[Settings](Seq(opt), desc, action)
  def boolean(opts: (String, String), desc: String, action: Settings => Settings) = new BooleanOption[Settings](Seq(opts._1, opts._2), desc, action)
  def string(opt: String, arg: String, desc: String, action: (Settings, String) => Settings) = new StringOption[Settings](Seq(opt), arg, desc, action)
  def int(opt: String, arg: String, desc: String, action: (Settings, Int) => Settings) = new IntOption[Settings](Seq(opt), arg, desc, action)
  def file(opt: String, arg: String, desc: String, action: (Settings, File) => Settings) = new FileOption[Settings](Seq(opt), arg, desc, action)
  def path(opt: String, arg: String, desc: String, action: (Settings, Seq[File]) => Settings) = new PathOption[Settings](Seq(opt), arg, desc, action)
  def path(opts: (String, String), arg: String, desc: String, action: (Settings, Seq[File]) => Settings) = new PathOption[Settings](Seq(opts._1, opts._2), arg, desc, action)
  def prefix(pre: String, arg: String, desc: String, action: (Settings, String) => Settings) = new PrefixOption[Settings](pre, arg, desc, action)
  def fileMap(opt: String, desc: String, action: (Settings, Map[File, File]) => Settings) = new FileMapOption[Settings](Seq(opt), desc, action)
  def header(label: String) = new HeaderOption[Settings](label)
  def dummy(opt: String, desc: String) = new DummyOption[Settings](opt, desc)
}
