// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.badscalastyle

/**
 * These comments are formmated incorrectly
 * and the parameter list is too long for one line
 */
case class ScalaStyle(one: String,two: String,three: String,four: String,
    five: String,six: String,seven: String,eight: String,  nine: String)

class Person(name: String,age: Int,astrologicalSign: String,
    shoeSize: Int,
    favoriteColor: java.awt.Color) {
  def getAge:Int={return age}
  def sum(longvariablename: List[String]): Int = {longvariablename.map(_.toInt).foldLeft(0)(_ + _)}
}