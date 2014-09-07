/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.inc.Analysis

object Util {

  def environment(property: String, env: String): Option[String] =
    Option(System.getProperty(property)) orElse Option(System.getenv(env))

  def lastCompile(analysis: Analysis): Long = {
    val times = analysis.apis.internal.values.map(_.compilation.startTime)
    if( times.isEmpty) 0L else times.max
  }
}
