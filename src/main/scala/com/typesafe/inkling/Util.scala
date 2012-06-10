/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import sbt.{ Level, Logger }

object Util {

  // logging

  val logCache = Cache[String, Logger](Setup.Defaults.loggerCacheLimit)

  def logger(quiet: Boolean, level: Level.Value): Logger = {
    logCache.get(logging(quiet, level))(newLogger(quiet, level))
  }

  def logging(quiet: Boolean, level: Level.Value): String = {
    if (quiet) "quiet" else level.toString
  }

  class SilentLogger extends Logger {
    def trace(t: => Throwable): Unit = ()
    def success(message: => String): Unit = ()
    def log(level: Level.Value, message: => String): Unit = ()
  }

  def newLogger(quiet: Boolean, level: Level.Value): Logger = {
    if (quiet) {
      new SilentLogger
    } else {
      val log = sbt.ConsoleLogger(); log.setLevel(level); log
    }
  }

  // time

  def timing(start: Long): String = {
    val end = System.currentTimeMillis
    "at %s [%s]" format (dateTime(end), duration(end - start))
  }

  def duration(millis: Long): String = {
    val secs = millis / 1000
    val (m, s, ms) = (secs / 60, secs % 60, millis % 1000)
    if (m > 0) "%d:%02d.%03ds" format (m, s, ms)
    else "%d.%03ds" format (s, ms)
  }

  def dateTime(time: Long): String = {
    java.text.DateFormat.getDateTimeInstance().format(new java.util.Date(time))
  }

  // normalising files

  def normalise(cwd: Option[File])(file: File): File = {
    if (cwd.isDefined && !file.isAbsolute) new File(cwd.get, file.getPath) else file
  }

  def normaliseOpt(cwd: Option[File])(optFile: Option[File]): Option[File] = {
    if (cwd.isDefined) optFile map normalise(cwd) else optFile
  }

  def normaliseSeq(cwd: Option[File])(files: Seq[File]): Seq[File] = {
    if (cwd.isDefined) files map normalise(cwd) else files
  }

  def normaliseMap(cwd: Option[File])(mapped: Map[File, File]): Map[File, File] = {
    if (cwd.isDefined) mapped map { case (l, r) => (normalise(cwd)(l), normalise(cwd)(r)) } else mapped
  }

  // properties

  def intProperty(name: String, default: Int): Int = {
    val value = System.getProperty(name)
    if (value ne null) try value.toInt catch { case _: Exception => default } else default
  }

  def stringSetProperty(name: String, default: Set[String]): Set[String] = {
    val value = System.getProperty(name)
    if (value ne null) (value split ",").toSet else default
  }

  def fileProperty(name: String): File = new File(System.getProperty(name, ""))

  def optFileProperty(name: String): Option[File] = Option(System.getProperty(name, null)).map(new File(_))

  def propertyFromResource(resource: String, property: String, classLoader: ClassLoader): Option[String] = {
    val props = propertiesFromResource(resource, classLoader)
    Option(props.getProperty(property))
  }

  def propertiesFromResource(resource: String, classLoader: ClassLoader): java.util.Properties = {
    val props = new java.util.Properties
    val stream = classLoader.getResourceAsStream(resource)
    try { props.load(stream) }
    catch { case e: Exception => }
    finally { stream.close }
    props
  }

  def setProperties(props: Seq[String]): Unit = {
    for (prop <- props) {
      val kv = prop split "="
      if (kv.length == 2) System.setProperty(kv(0), kv(1))
    }
  }

  // debug output

  def show(thing: Any, output: String => Unit, prefix: String = "", level: Int = 0): Unit = {
    def out(s: String) = output(("   " * level) + s)
    thing match {
      case (label: Any, value: Any) => show(value, output, label.toString + " = ", level)
      case Some(value: Any) => show(value, output, prefix, level)
      case None => out(prefix)
      case t: Traversable[_] if t.isEmpty => out(prefix + "{}")
      case t: Traversable[_] =>
        out(prefix + "{")
        t foreach { a => show(a, output, "", level + 1) }
        out("}")
      case any => out(prefix + any.toString)
    }
  }
}
