/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import java.util.{ Date, TimeZone }
import sbt._
import sbt.inc.Analysis
import sbt.Keys._

object Version {
  val currentCommit = TaskKey[String]("current-commit")

  lazy val settings: Seq[Setting[_]]  = Seq(
    currentCommit <<= (baseDirectory, streams) map gitCommitHash,
    resourceGenerators in Compile <+= (version, currentCommit, resourceManaged, compile in Compile, streams) map generateFile
  )

  def gitCommitHash(dir: File, s: TaskStreams): String = {
    try { Process(Seq("git", "rev-parse", "HEAD"), dir) !! s.log }
    catch { case e: Exception => "unknown" }
  }

  def generateFile(version: String, commit: String, dir: File, analysis: Analysis, s: TaskStreams): Seq[File] = {
    val file = dir / "inkling.version.properties"
    val formatter = new java.text.SimpleDateFormat("yyyyMMdd-HHmmss")
    formatter.setTimeZone(TimeZone.getTimeZone("GMT"))
    val timestamp = formatter.format(new Date)
    val content = """
      |version=%s
      |timestamp=%s
      |commit=%s
      """.trim.stripMargin format (version, timestamp, commit)
    if (!file.exists || file.lastModified < Util.lastCompile(analysis)) {
      s.log.info("Generating version file: " + file)
      IO.write(file, content)
    }
    Seq(file)
  }
}
