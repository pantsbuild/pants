grammar bogus;


options {
	language=Python;
	output=AST;
	ASTLabelType=CommonTree;
}

file
    : this is intentionally bogus
