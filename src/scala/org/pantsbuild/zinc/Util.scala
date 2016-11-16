/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import sbt.io.{ Hash, IO }
import sbt.io.syntax._

object Util {
  //
  // Time
  //

  /**
   * Current timestamp and time passed since start time.
   */
  def timing(start: Long): String = {
    val end = System.currentTimeMillis
    "at %s [%s]" format (dateTime(end), duration(end - start))
  }

  /**
   * Format a minutes:seconds.millis time.
   */
  def duration(millis: Long): String = {
    val secs = millis / 1000
    val (m, s, ms) = (secs / 60, secs % 60, millis % 1000)
    if (m > 0) "%d:%02d.%03ds" format (m, s, ms)
    else "%d.%03ds" format (s, ms)
  }

  /**
   * Creating a readable timestamp.
   */
  def dateTime(time: Long): String = {
    java.text.DateFormat.getDateTimeInstance().format(new java.util.Date(time))
  }

  //
  // Files
  //

  /**
   * Normalise file in relation to actual current working directory.
   */
  def normalise(cwd: Option[File])(file: File): File = {
    if (cwd.isDefined && !file.isAbsolute) new File(cwd.get, file.getPath) else file
  }

  /**
   * Normalise optional file in relation to actual current working directory.
   */
  def normaliseOpt(cwd: Option[File])(optFile: Option[File]): Option[File] = {
    if (cwd.isDefined) optFile map normalise(cwd) else optFile
  }

  /**
   * Normalise file pair in relation to actual current working directory.
   */
  def normalisePair(cwd: Option[File])(pair: (File, File)): (File, File) = {
    if (cwd.isDefined) (normalise(cwd)(pair._1), normalise(cwd)(pair._2)) else pair
  }

  /**
   * Normalise sequence of files in relation to actual current working directory.
   */
  def normaliseSeq(cwd: Option[File])(files: Seq[File]): Seq[File] = {
    if (cwd.isDefined) files map normalise(cwd) else files
  }

  /**
   * Normalise file map in relation to actual current working directory.
   */
  def normaliseMap(cwd: Option[File])(mapped: Map[File, File]): Map[File, File] = {
    if (cwd.isDefined) mapped map { case (l, r) => (normalise(cwd)(l), normalise(cwd)(r)) } else mapped
  }

  /**
   * Normalise file sequence map in relation to actual current working directory.
   */
  def normaliseSeqMap(cwd: Option[File])(mapped: Map[Seq[File], File]): Map[Seq[File], File] = {
    if (cwd.isDefined) mapped map { case (l, r) => (normaliseSeq(cwd)(l), normalise(cwd)(r)) } else mapped
  }

  /**
   * Fully relativize a path, relative to any other base.
   */
  def relativize(base: File, path: File): String = {
    import scala.tools.nsc.io.Path._
    (base relativize path).toString
  }

  /**
   * Check a file is writable.
   */
  def checkWritable(file: File) = {
    if (file.exists) file.canWrite else file.getParentFile.canWrite
  }

  /**
   * Clean all class files from a directory.
   */
  def cleanAllClasses(dir: File): Unit = {
    import sbt.io.Path._
    IO.delete((dir ** "*.class").get)
  }

  /**
   * Hash of a file's canonical path.
   */
  def pathHash(file: File): String = {
    Hash.toHex(Hash(file.getCanonicalPath))
  }

  //
  // Properties
  //

  /**
   * Create int from system property.
   */
  def intProperty(name: String, default: Int): Int = {
    val value = System.getProperty(name)
    if (value ne null) try value.toInt catch { case _: Exception => default } else default
  }

  /**
   * Create set of strings, split by comma, from system property.
   */
  def stringSetProperty(name: String, default: Set[String]): Set[String] = {
    val value = System.getProperty(name)
    if (value ne null) (value split ",").toSet else default
  }

  /**
   * Create a file, default empty, from system property.
   */
  def fileProperty(name: String): File = new File(System.getProperty(name, ""))

  /**
   * Create an option file from system property.
   */
  def optFileProperty(name: String): Option[File] = Option(System.getProperty(name, null)).map(new File(_))

  /**
   * Get a property from a properties file resource in the classloader.
   */
  def propertyFromResource(resource: String, property: String, classLoader: ClassLoader): Option[String] = {
    val props = propertiesFromResource(resource, classLoader)
    Option(props.getProperty(property))
  }

  /**
   * Get all properties from a properties file resource in the classloader.
   */
  def propertiesFromResource(resource: String, classLoader: ClassLoader): java.util.Properties = {
    val props = new java.util.Properties
    val stream = classLoader.getResourceAsStream(resource)
    try { props.load(stream) }
    catch { case e: Exception => }
    finally { if (stream ne null) stream.close }
    props
  }

  /**
   * Set system properties.
   */
  def setProperties(props: Seq[String]): Unit = {
    for (prop <- props) {
      val kv = prop split "="
      if (kv.length == 2) System.setProperty(kv(0), kv(1))
    }
  }

  //
  // Timers
  //

  /**
   * Simple duration regular expression.
   */
  val Duration = """(\d+)([hms])""".r

  /**
   * Milliseconds from string duration of the form Nh|Nm|Ns, otherwise default.
   */
  def duration(arg: String, default: Long): Long =
    arg match {
      case Duration(length, unit) =>
        val multiplier = unit match {
          case "h" => 60 * 60 * 1000
          case "m" => 60 * 1000
          case "s" => 1000
          case _   => 0
        }
        try { length.toLong * multiplier } catch { case _: Exception => default }
      case _ => default
    }

  /**
   * Schedule a resettable timer.
   */
  def timer(delay: Long)(body: => Unit) = new Alarm(delay)(body)

  /**
   * Resettable timer.
   */
  class Alarm(delay: Long)(body: => Unit) {
    import java.util.{ Timer, TimerTask }

    private[this] var timer: Timer = _
    private[this] var task: TimerTask = _

    schedule()

    private[this] def schedule(): Unit = {
      if ((task eq null) && delay > 0) {
        if (timer eq null) timer = new Timer(true) // daemon = true
        task = new TimerTask { def run = body }
        timer.schedule(task, delay)
      }
    }

    def reset(): Unit = synchronized {
      if (task ne null) { task.cancel(); task = null }
      schedule()
    }

    def cancel(): Unit = if (timer ne null) timer.cancel()
  }

  //
  // Debug output
  //

  /**
   * General utility for displaying objects for debug output.
   */
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

  def counted(count: Int, prefix: String, single: String, plural: String): String = {
    count.toString + " " + prefix + (if (count == 1) single else plural)
  }
}
