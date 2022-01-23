package co.actioniq.cryptography

import org.mindrot.jbcrypt.BCrypt

object Hashing {
  def foo(): String = BCrypt.gensalt()
}
