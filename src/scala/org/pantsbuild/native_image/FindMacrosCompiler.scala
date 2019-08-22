package org.pantsbuild.native_image

import scala.tools.asm._
import scala.tools.scalap.scalax.rules.scalasig._
import scala.reflect.NameTransformer
import scala.tools.nsc.interactive.Global
import scala.tools.nsc.Settings
import scala.tools.nsc.reporters.ConsoleReporter
import scala.reflect.io.VirtualDirectory

/**
 * Wrapper around a scala-compiler Global instance with helper methods to
 * extract information from macro definition annotations.
 */
class FindMacrosCompiler(classpath: String) {
  private val g = newCompiler(classpath)

  def shutdown(): Unit = g.askShutdown()

  def macroClassName(scalapSymbol: Symbol): List[String] = synchronized {
    for {
      scalacSymbol <- compilerSymbol(scalapSymbol).alternatives
      scalacAnnotation <- scalacSymbol.annotations
      // See documentation for `scala.tools.nsc.typechecker.MacroImplBinding`
      // for details about the structure of the `@macroImpl` annotation.
      className <- scalacAnnotation.args match {
        case List(apply) =>
          treeArguments(apply).collect {
            case g.Assign(
                g.Literal(g.Constant("className")),
                g.Literal(g.Constant(fqn: String))
                ) =>
              fqn
          }
        case _ => Nil
      }
    } yield className
  }

  private def newCompiler(classpath: String): Global = {
    val settings = new Settings()
    val vd = new VirtualDirectory("(memory)", None)
    settings.classpath.value = classpath
    settings.outputDirs.setSingleOutput(vd)
    settings.YpresentationAnyThread.value = true
    val reporter = new ConsoleReporter(settings)
    new Global(settings, reporter)
  }

  private def isTermSymbol(scalapSymbol: Symbol): Boolean =
    scalapSymbol match {
      case _: ObjectSymbol   => true
      case _: MethodSymbol   => true
      case s: ExternalSymbol => s.entry.entryType == 10
      case c: ClassSymbol    => c.isModule
      case _                 => false
    }

  // Returns a Scala compiler symbol given a scalap Symbol.
  private def compilerSymbol(scalapSymbol: Symbol): g.Symbol = {
    val encoded = NameTransformer.encode(scalapSymbol.name)
    val name =
      if (isTermSymbol(scalapSymbol)) g.TermName(encoded)
      else g.TypeName(encoded)
    val result = scalapSymbol.parent match {
      case None        => g.findMemberFromRoot(name)
      case Some(value) => compilerSymbol(value).info.decl(name)
    }
    result
  }

  private def treeArguments(t: g.Tree): List[g.Tree] = t match {
    case g.Apply(_, as)      => as
    case g.TypeApply(fun, _) => treeArguments(fun)
  }
}