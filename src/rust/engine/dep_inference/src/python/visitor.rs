#[derive(Debug, PartialEq)]
pub enum ChildBehavior {
    Visit,
    Ignore,
}
#[allow(unused_variables)]
pub trait Visitor {
  fn visit_identifier(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_ellipsis(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_escape_sequence(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_type_conversion(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_integer(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_float(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_true(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_false(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_none(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_comment(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_module(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_import_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_import_prefix(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_relative_import(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_future_import_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_import_from_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_aliased_import(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_wildcard_import(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_print_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_chevron(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_assert_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_expression_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_named_expression(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_return_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_delete_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_raise_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_pass_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_break_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_continue_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_if_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_elif_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_else_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_match_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_case_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_for_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_while_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_try_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_except_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_finally_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_with_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_with_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_with_item(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_function_definition(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_parameters(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_lambda_parameters(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_list_splat(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_dictionary_splat(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_global_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_nonlocal_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_exec_statement(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_class_definition(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_parenthesized_list_splat(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_argument_list(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_decorated_definition(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_decorator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_block(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_expression_list(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_dotted_name(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_tuple_pattern(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_list_pattern(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_default_parameter(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_typed_default_parameter(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_list_splat_pattern(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_dictionary_splat_pattern(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_as_pattern(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_not_operator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_boolean_operator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_binary_operator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_unary_operator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_comparison_operator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_lambda(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_assignment(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_augmented_assignment(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_pattern_list(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_yield(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_attribute(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_subscript(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_slice(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_call(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_typed_parameter(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_type(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_keyword_argument(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_list(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_set(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_tuple(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_dictionary(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_pair(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_list_comprehension(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_dictionary_comprehension(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_set_comprehension(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_generator_expression(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_parenthesized_expression(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_for_in_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_if_clause(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_conditional_expression(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_concatenated_string(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_string(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_interpolation(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_format_specifier(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_format_expression(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_await(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_positional_separator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_keyword_separator(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_as_pattern_target(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }
  fn visit_case_pattern(&mut self, node: tree_sitter::Node) -> ChildBehavior { ChildBehavior::Visit }

  fn visit(&mut self, node: tree_sitter::Node) -> ChildBehavior {
      match node.kind_id() {
        1 => self.visit_identifier(node),
        83 => self.visit_ellipsis(node),
        88 => self.visit_escape_sequence(node),
        91 => self.visit_type_conversion(node),
        92 => self.visit_integer(node),
        93 => self.visit_float(node),
        95 => self.visit_true(node),
        96 => self.visit_false(node),
        97 => self.visit_none(node),
        98 => self.visit_comment(node),
        105 => self.visit_module(node),
        108 => self.visit_import_statement(node),
        109 => self.visit_import_prefix(node),
        110 => self.visit_relative_import(node),
        111 => self.visit_future_import_statement(node),
        112 => self.visit_import_from_statement(node),
        114 => self.visit_aliased_import(node),
        115 => self.visit_wildcard_import(node),
        116 => self.visit_print_statement(node),
        117 => self.visit_chevron(node),
        118 => self.visit_assert_statement(node),
        119 => self.visit_expression_statement(node),
        120 => self.visit_named_expression(node),
        122 => self.visit_return_statement(node),
        123 => self.visit_delete_statement(node),
        124 => self.visit_raise_statement(node),
        125 => self.visit_pass_statement(node),
        126 => self.visit_break_statement(node),
        127 => self.visit_continue_statement(node),
        128 => self.visit_if_statement(node),
        129 => self.visit_elif_clause(node),
        130 => self.visit_else_clause(node),
        131 => self.visit_match_statement(node),
        132 => self.visit_case_clause(node),
        133 => self.visit_for_statement(node),
        134 => self.visit_while_statement(node),
        135 => self.visit_try_statement(node),
        136 => self.visit_except_clause(node),
        137 => self.visit_finally_clause(node),
        138 => self.visit_with_statement(node),
        139 => self.visit_with_clause(node),
        140 => self.visit_with_item(node),
        141 => self.visit_function_definition(node),
        142 => self.visit_parameters(node),
        143 => self.visit_lambda_parameters(node),
        144 => self.visit_list_splat(node),
        145 => self.visit_dictionary_splat(node),
        146 => self.visit_global_statement(node),
        147 => self.visit_nonlocal_statement(node),
        148 => self.visit_exec_statement(node),
        149 => self.visit_class_definition(node),
        150 => self.visit_parenthesized_list_splat(node),
        151 => self.visit_argument_list(node),
        152 => self.visit_decorated_definition(node),
        153 => self.visit_decorator(node),
        154 => self.visit_block(node),
        155 => self.visit_expression_list(node),
        156 => self.visit_dotted_name(node),
        161 => self.visit_tuple_pattern(node),
        162 => self.visit_list_pattern(node),
        163 => self.visit_default_parameter(node),
        164 => self.visit_typed_default_parameter(node),
        165 => self.visit_list_splat_pattern(node),
        166 => self.visit_dictionary_splat_pattern(node),
        167 => self.visit_as_pattern(node),
        171 => self.visit_not_operator(node),
        172 => self.visit_boolean_operator(node),
        173 => self.visit_binary_operator(node),
        174 => self.visit_unary_operator(node),
        175 => self.visit_comparison_operator(node),
        176 => self.visit_lambda(node),
        177 => self.visit_lambda(node),
        178 => self.visit_assignment(node),
        179 => self.visit_augmented_assignment(node),
        180 => self.visit_pattern_list(node),
        182 => self.visit_yield(node),
        183 => self.visit_attribute(node),
        184 => self.visit_subscript(node),
        185 => self.visit_slice(node),
        186 => self.visit_call(node),
        187 => self.visit_typed_parameter(node),
        188 => self.visit_type(node),
        189 => self.visit_keyword_argument(node),
        190 => self.visit_list(node),
        191 => self.visit_set(node),
        192 => self.visit_tuple(node),
        193 => self.visit_dictionary(node),
        194 => self.visit_pair(node),
        195 => self.visit_list_comprehension(node),
        196 => self.visit_dictionary_comprehension(node),
        197 => self.visit_set_comprehension(node),
        198 => self.visit_generator_expression(node),
        200 => self.visit_parenthesized_expression(node),
        202 => self.visit_for_in_clause(node),
        203 => self.visit_if_clause(node),
        204 => self.visit_conditional_expression(node),
        205 => self.visit_concatenated_string(node),
        206 => self.visit_string(node),
        207 => self.visit_interpolation(node),
        209 => self.visit_format_specifier(node),
        210 => self.visit_format_expression(node),
        211 => self.visit_await(node),
        212 => self.visit_positional_separator(node),
        213 => self.visit_keyword_separator(node),
        241 => self.visit_as_pattern_target(node),
        242 => self.visit_case_pattern(node),
        _ => ChildBehavior::Visit,
    }
  }
}
