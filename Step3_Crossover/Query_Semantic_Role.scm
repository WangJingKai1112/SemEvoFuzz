;; Contexts used by ast_information.get_node_roles. Captures intentionally
;; select complete expressions; identifiers inside each capture receive the role.
(for_statement
  initializer: (_) @loop_control)
(for_statement
  condition: (_) @loop_control)
(for_statement
  update: (_) @loop_control)

(if_statement
  condition: (_) @condition)
(while_statement
  condition: (_) @condition)
(do_statement
  condition: (_) @condition)
(switch_statement
  condition: (_) @condition)

(subscript_expression
  index: (_) @array_index)

(return_statement (_) @return_related)

(assignment_expression
  left: (_) @assignment_left
  right: (_) @assignment_right)
