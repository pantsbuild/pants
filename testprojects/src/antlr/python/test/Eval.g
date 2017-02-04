tree grammar Eval;

options {
    language=Python;
    tokenVocab=Expr;
    ASTLabelType=CommonTree;
}

@init {self.memory = {}}

// START:stat
prog:   stat+ ;

stat:   expr
        {print $expr.value}
    |   ^('=' ID expr)
        {self.memory[$ID.getText()] = int($expr.value)}
    ;
// END:stat

// START:expr
expr returns [value]
    :   ^('+' a=expr b=expr) {$value = a+b;}
    |   ^('-' a=expr b=expr) {$value = a-b;}
    |   ^('*' a=expr b=expr) {$value = a*b;}
    |   ID
        {
k = $ID.getText()
if k in self.memory:
	$value = self.memory[k]
else:
	print >> sys.stderr, "undefined variable "+k
        }
    |   INT {$value = int($INT.getText())}
    ;
// END:expr
