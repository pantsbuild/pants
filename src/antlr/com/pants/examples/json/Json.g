// for testing purposes

grammar Json;

options {
  language=Java;
  output=AST;
  ASTLabelType=CommonTree;
}

object
  : OBRACE (kvpair (COMMA kvpair)*)? CBRACE
  ;

array
  : OBRACKET (value (COMMA value)*)? CBRACKET
  ;

value 
  : string
  | number
  | object
  | array
  | TRUE
  | FALSE
  | NULL
  ;

string
  : DQUOTE LOOSE_CHAR* DQUOTE
  ;

number
  : DASH ? (ZERO | (DIGIT19 DIGIT*)) (DOT DIGIT+)? EXPONENT?
  ;

LOOSE_CHAR
  : STRICT_CHAR 
  | ESCAPED
  ;

STRICT_CHAR
  : '\u0000' .. '\u0021'
  | '\u0023' .. '\u005b'
  | '\u005d' .. '\uffff'
  ;

ESCAPED
  : '\\' (DQUOTE | '\\' | '/' | 'b' | 'f' | 'n' | 'r' | 't' | ('u' HEX HEX HEX HEX))
  ;

kvpair
  : string COLON value
  ;

DIGIT19
  : '1' .. '9'
  ;

DIGIT
  : '0' .. '9'
  ;

EXPONENT
  : ('e'|'E') ('+'|'-')? DIGIT+
  ;

ZERO
  : '\u0030'
  ;

DOT
  : '\u002e'
  ;

COLON
  : '\u003a'
  ;

DASH
  : '\u002d'
  ;

DQUOTE
  : '\u0022'
  ;

OBRACE
  : '{'
  ;

CBRACE
  : '}'
  ;

OBRACKET
  : '['
  ;

CBRACKET
  : ']'
  ;

TRUE
  : 'true'
  ;

FALSE
  : 'false'
  ;

NULL
  : 'null'
  ;

COMMA
  : ','
  ;

HEX
  : '\u0030' .. '\u0039'
  | '\u0061' .. '\u0066'
  | '\u0041' .. '\u0046'
  ;