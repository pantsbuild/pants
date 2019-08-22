package org.pantsbuild.native_image

import scala.tools.asm._
import scala.meta.internal.io._
import scala.meta.internal.metacp._
import scala.meta.io.Classpath
import scala.tools.scalap.scalax.rules.scalasig._
import scala.collection.mutable

object FindMacros {
  def main(args: Array[String]): Unit = {
    if (args.isEmpty) {
      println("Missing argument <classpath>, see --help.")
      System.exit(1)
    } else if (args.sameElements(Array("--help"))) {
      println(
        """|usage: find-macros <classpath>
           |
           |Given a JVM classpath, prints out the fully qualified JVM names
           |of classes |that define Scala macros. The classpath is formatted
           |as a path separated |list of paths to jar files, example
           |"a.jar:b.jar:c.jar".
           |""".stripMargin
      )
    } else {
      val classNames = run(args(0))
      classNames.foreach { className =>
        println(className)
      }
    }
  }

  def run(classpath: String): Iterable[String] = {
    val compiler = new FindMacrosCompiler(classpath)
    val classNames = mutable.Set.empty[String]
    Classpath(classpath).entries.par.foreach { jar =>
      Classpath(jar).foreach { jarRoot =>
        for {
          classfile <- FileIO.listAllFilesRecursively(jarRoot.path).iterator
          if classfile.toNIO.getFileName().toString().endsWith(".class")
          scalapSignature <- classfile.toClassNode.scalaSig.iterator
          scalapSymbol <- scalapSignature.scalaSig.symbols.iterator.collect {
            case sig: SymbolInfoSymbol => sig
          }
          if scalapSymbol.isMethod
          scalapAnnotation <- scalapSymbol.attributes
          className <- scalapAnnotation.typeRef match {
            // The Scala compiler generates a `@macroImpl(...)` annotation
            // for every macro definition such as `def foo: Int = macro impl`.
            case tpe: TypeRefType if tpe.symbol.name == "macroImpl" =>
              compiler.macroClassName(scalapSymbol)
            case _ =>
              Nil
          }
        } {
          classNames += className
        }
      }
    }
    compiler.shutdown()
    classNames
  }
}
