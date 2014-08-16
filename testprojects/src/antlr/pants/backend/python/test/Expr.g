grammar Expr;

options {
	language=Python;
	output=AST;
	ASTLabelType=CommonTree;
}

prog	: ( stat {print $stat.tree.toStringTree();} )+ ;

stat	:	expr NEWLINE        -> expr
	|	ID '=' expr NEWLINE -> ^('=' ID expr)
	|	NEWLINE             ->
	;

expr	:	multExpr (('+'^|'-'^) multExpr)*
	;

multExpr
	:	atom ('*'^ atom)*
	;

atom	:	INT
	|	ID
	|	'('! expr ')'!
	;

ID	:	('a'..'z'|'A'..'Z')+ ;

INT	:	'0'..'9'+ ;

NEWLINE	:	'\r'? '\n' ;

WS	:	(' '|'\t'|'\n'|'\r')+ {self.skip()} ;

