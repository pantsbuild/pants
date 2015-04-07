/*
 * http://stackoverflow.com/questions/1931307/antlr-is-there-a-simple-example
 * Modified for antlr4
 *
 * Evaluate expressions using the 4 basic math operatiors: +, -, /, * and nest
 * with parenthesis.
 */

grammar ExpAntlr4;


eval returns [double value]
    :    exp=additionExp {$value = $exp.value;}
    ;

additionExp returns [double value]
    :    m1=multiplyExp       {$value =  $m1.value;}
         ( '+' m2=multiplyExp {$value += $m2.value;}
         | '-' m2=multiplyExp {$value -= $m2.value;}
         )*
    ;

multiplyExp returns [double value]
    :    a1=atomExp       {$value =  $a1.value;}
         ( '*' a2=atomExp {$value *= $a2.value;}
         | '/' a2=atomExp {$value /= $a2.value;}
         )*
    ;

atomExp returns [double value]
    :    n=Number                {$value = Double.parseDouble($n.text);}
    |    '(' exp=additionExp ')' {$value = $exp.value;}
    ;

Number
    :    ('0'..'9')+ ('.' ('0'..'9')+)?
    ;

WS
    :   (' ' | '\t' | '\r'| '\n') -> skip
    ;
