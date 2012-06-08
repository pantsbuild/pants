/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import sbt.Level
import sbt.Path._
import xsbti.compile.CompileOrder

case class Settings(
  help: Boolean = false,
  version: Boolean = false,
  quiet: Boolean = false,
  logLevel: Level.Value = Level.Info,
  sources: Seq[File] = Seq.empty,
  classpath: Seq[File] = Seq.empty,
  classesDirectory: File = new File("."),
  scalaHome: Option[File] = None,
  scalaCompiler: Option[File] = None,
  scalaLibrary: Option[File] = None,
  scalacOptions: Seq[String] = Seq.empty,
  javaHome: Option[File] = None,
  javaOnly: Boolean = false,
  javacOptions: Seq[String] = Seq.empty,
  compileOrder: CompileOrder = CompileOrder.Mixed,
  analysisCache: Option[File] = None,
  analysisMap: Map[File, File] = Map.empty,
  residentLimit: Int = 0,
  properties: Seq[String] = Seq.empty)

object Settings {
  val options = Seq(
    boolean( ("-help", "-h"),                "Print this usage message",                   (s: Settings) => s.copy(help = true)),
    boolean( "-version",                     "Print version",                              (s: Settings) => s.copy(version = true)),
    boolean( ("-quiet", "-q"),               "Silence all logging",                        (s: Settings) => s.copy(quiet = true)),
    boolean( "-debug",                       "Set log level to debug",                     (s: Settings) => s.copy(logLevel = Level.Debug)),
    string(  "-log-level", "level",          "Set log level (debug|info|warn|error)",      (s: Settings, l: String) => s.copy(logLevel = Level.withName(l))),
    path(    ("-classpath", "-cp"), "path",  "Specify the classpath",                      (s: Settings, cp: Seq[File]) => s.copy(classpath = cp)),
    file(    "-d", "directory",              "Destination for compiled classes",           (s: Settings, f: File) => s.copy(classesDirectory = f)),
    file(    "-scala-home", "directory",     "Scala home directory (for locating jars)",   (s: Settings, f: File) => s.copy(scalaHome = Some(f))),
    file(    "-scala-compiler", "jar",       "Location of Scala compiler",                 (s: Settings, f: File) => s.copy(scalaCompiler = Some(f))),
    file(    "-scala-library", "jar",        "Location of Scala library",                  (s: Settings, f: File) => s.copy(scalaLibrary = Some(f))),
    prefix(  "-S", "<scalac-option>",        "Pass option to scalac",                      (s: Settings, o: String) => s.copy(scalacOptions = s.scalacOptions :+ o)),
    file(    "-java-home", "directory",      "Java home directory (to select javac)",      (s: Settings, f: File) => s.copy(javaHome = Some(f))),
    prefix(  "-J", "<javac-option>",         "Pass option to javac",                       (s: Settings, o: String) => s.copy(javacOptions = s.javacOptions :+ o)),
    boolean( "-java-only",                   "Don't add scala library to classpath",       (s: Settings) => s.copy(javaOnly = true)),
    string(  "-compile-order", "order",      "Compile order for Scala and Java sources",   (s: Settings, o: String) => s.copy(compileOrder = compileOrder(o))),
    file(    "-analysis-cache", "file",      "Cache file for compile analysis",            (s: Settings, f: File) => s.copy(analysisCache = Some(f))),
    fileMap( "-analysis-map",                "Upstream analysis mapping (file:file,...)",  (s: Settings, m: Map[File, File]) => s.copy(analysisMap = m)),
    int(     "-resident-limit", "int",       "Set maximum number of resident compilers",   (s: Settings, i: Int) => s.copy(residentLimit = i)),
    prefix(  "-D", "property=value",         "Pass property to runtime system",            (s: Settings, o: String) => s.copy(properties = s.properties :+ o)),
    dummy(   "-V<flag>",                     "Set JVM flag directly for this process"),
    dummy(   "-nailed",                      "Run as daemon with nailgun server"),
    dummy(   "-port",                        "Set nailgun port (if nailed)"),
    dummy(   "-status",                      "Report nailgun server status (if nailed)"),
    dummy(   "-shutdown",                    "Shutdown nailgun server (if nailed)")
  )

  val allOptions: Set[OptionDef[Settings]] = options.toSet

  def printUsage(): Unit = {
    val column = options.map(_.help.length).max + 2
    println("Usage: %s <options> <sources>" format Setup.Command)
    options foreach { opt => println("  " + opt.help.padTo(column, ' ') + opt.description) }
    println()
  }

  def isOpt(s: String) = s startsWith "-"

  def parse(args: Seq[String]): Parsed[Settings] = {
    val Parsed(settings, remaining, errors) = Options.parse(Settings(), allOptions, args, stopOnError = false)
    val (unknown, residual) = remaining partition isOpt
    val sources = residual map (new File(_))
    val unknownErrors = unknown map ("Unknown option: " + _)
    Parsed(settings.copy(sources = sources), Seq.empty, errors ++ unknownErrors)
  }

  def compileOrder(order: String): CompileOrder = {
    order.toLowerCase match {
      case "mixed"                                       => CompileOrder.Mixed
      case "java"  | "java-then-scala" | "javathenscala" => CompileOrder.JavaThenScala
      case "scala" | "scala-then-java" | "scalathenjava" => CompileOrder.ScalaThenJava
    }
  }

  def normalise(settings: Settings, cwd: Option[File]): Settings = {
    if (cwd.isEmpty) settings
    else {
      import settings._
      settings.copy(
        sources = Util.normaliseSeq(cwd)(sources),
        classpath = Util.normaliseSeq(cwd)(classpath),
        classesDirectory = Util.normalise(cwd)(classesDirectory),
        scalaHome = Util.normaliseOpt(cwd)(scalaHome),
        scalaCompiler = Util.normaliseOpt(cwd)(scalaCompiler),
        scalaLibrary = Util.normaliseOpt(cwd)(scalaLibrary),
        javaHome = Util.normaliseOpt(cwd)(javaHome),
        analysisCache = Util.normaliseOpt(cwd)(analysisCache),
        analysisMap = Util.normaliseMap(cwd)(analysisMap)
      )
    }
  }

  def boolean(opt: String, desc: String, action: Settings => Settings) = new BooleanOption[Settings](Seq(opt), desc, action)
  def boolean(opts: (String, String), desc: String, action: Settings => Settings) = new BooleanOption[Settings](Seq(opts._1, opts._2), desc, action)
  def string(opt: String, arg: String, desc: String, action: (Settings, String) => Settings) = new StringOption[Settings](Seq(opt), arg, desc, action)
  def int(opt: String, arg: String, desc: String, action: (Settings, Int) => Settings) = new IntOption[Settings](Seq(opt), arg, desc, action)
  def file(opt: String, arg: String, desc: String, action: (Settings, File) => Settings) = new FileOption[Settings](Seq(opt), arg, desc, action)
  def path(opts: (String, String), arg: String, desc: String, action: (Settings, Seq[File]) => Settings) = new PathOption[Settings](Seq(opts._1, opts._2), arg, desc, action)
  def prefix(pre: String, arg: String, desc: String, action: (Settings, String) => Settings) = new PrefixOption[Settings](pre, arg, desc, action)
  def fileMap(opt: String, desc: String, action: (Settings, Map[File, File]) => Settings) = new FileMapOption[Settings](Seq(opt), desc, action)
  def dummy(opt: String, desc: String) = new DummyOption[Settings](opt, desc)
}
