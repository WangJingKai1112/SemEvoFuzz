import re
from typing import Dict, List, Optional, Set

import numpy as np
import tree_sitter
from tree_sitter import Language, Parser


LANGUAGE = Language("Libs/tree_sitter/parser/my-languages.so", "c")
parser = Parser()
parser.set_language(LANGUAGE)

VALUE = "value"
STRUCTURAL = "structural"

ARITHMETIC = ["+", "-", "*", "/"]
COMPARISONS = ["<", ">", "<=", ">=", "==", "!="]
INTEGER_TYPES = ["int", "unsigned", "long", "short"]


def _text(code: str, node) -> str:
    return code.encode("utf-8")[node.start_byte:node.end_byte].decode(
        "utf-8", errors="replace"
    )


def _node_text(node) -> str:
    value = node.text
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _walk(node):
    yield node
    for child in node.children:
        for descendant in _walk(child):
            yield descendant


def _contains(node, node_types: Set[str]) -> bool:
    return any(item.type in node_types for item in _walk(node))


def _identifiers(node) -> Set[str]:
    return {_text_from_node(item) for item in _walk(node) if item.type == "identifier"}


def _text_from_node(node) -> str:
    value = node.text
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _target(kind: str, category: str, node, choices: int, initial: int = 0, **extra):
    result = {
        "kind": kind,
        "category": category,
        "node": node,
        "choices": choices,
        "initial": initial,
    }
    result.update(extra)
    return result


def _operator_target(node) -> Optional[Dict]:
    for child in node.children:
        if child.type in ARITHMETIC:
            return _target(
                "op", VALUE, child, len(ARITHMETIC), ARITHMETIC.index(child.type)
            )
    return None


def _comparison_target(node) -> Optional[Dict]:
    for child in node.children:
        if child.type in COMPARISONS:
            return _target(
                "compare", VALUE, child, len(COMPARISONS), COMPARISONS.index(child.type)
            )
    return None


def _direct_number(node):
    if node is None:
        return None
    return next((item for item in _walk(node) if item.type == "number_literal"), None)


def _integer_literal_node(code: str, node):
    """Return the complete signed integer literal node, or None for floats."""
    if node is None or node.type != "number_literal":
        return None
    literal = _text(code, node).strip()
    if not re.fullmatch(
        r"[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]*|[0-9]+)[uUlL]*",
        literal,
    ):
        return None
    parent = node.parent
    if parent is not None and parent.type == "unary_expression":
        operator = next((child.type for child in parent.children if child.type in {"+", "-"}), None)
        named = list(parent.named_children)
        if operator is not None and len(named) == 1 and named[0] == node:
            return parent
    return node


def _inside_array_dimension(node) -> bool:
    parent = node.parent
    while parent is not None and parent.type not in {
        "function_definition", "compound_statement", "translation_unit"
    }:
        if parent.type == "array_declarator":
            size = parent.child_by_field_name("size")
            return size is not None and size.start_byte <= node.start_byte < size.end_byte
        parent = parent.parent
    return False


def _condition_expression(condition):
    current = condition
    while current is not None and current.type == "parenthesized_expression":
        current = next(iter(current.named_children), None)
    return current


def _local_integer_declaration(code: str, node) -> Optional[Dict]:
    if node.parent is None or node.parent.type != "compound_statement":
        return None
    declarators = [
        item for item in node.named_children
        if item.type in {
            "init_declarator", "identifier", "pointer_declarator",
            "array_declarator", "function_declarator",
        }
    ]
    if len(declarators) != 1:
        return None
    if _contains(node, {"pointer_declarator", "array_declarator", "function_declarator"}):
        return None
    type_node = next(
        (item for item in node.named_children
         if item.type in {"primitive_type", "sized_type_specifier"}),
        None,
    )
    if type_node is None:
        return None
    type_text = _text(code, type_node).strip()
    normalized = "unsigned" if type_text == "unsigned int" else type_text
    if normalized not in INTEGER_TYPES:
        return None
    return _target(
        "integer_type", VALUE, type_node, len(INTEGER_TYPES),
        INTEGER_TYPES.index(normalized),
    )


def _volatile_target(code: str, node) -> Optional[Dict]:
    if node.parent is None or node.parent.type != "compound_statement":
        return None
    qualifier = next(
        (item for item in node.named_children
         if item.type == "type_qualifier" and _text(code, item).strip() == "volatile"),
        None,
    )
    return _target(
        "volatile", VALUE, node, 2, 1 if qualifier is not None else 0,
        qualifier=qualifier,
    )


def _call_sequence_targets(node) -> List[Dict]:
    targets = []
    named = list(node.named_children)

    for index in range(len(named) - 1):
        first, second = named[index], named[index + 1]
        if first.type != "expression_statement" or second.type != "expression_statement":
            continue
        first_expressions = list(first.named_children)
        second_expressions = list(second.named_children)
        if (len(first_expressions) != 1 or len(second_expressions) != 1 or
                first_expressions[0].type != "call_expression" or
                second_expressions[0].type != "call_expression"):
            continue
        first_call = first_expressions[0]
        second_call = second_expressions[0]
        first_fn = first_call.child_by_field_name("function")
        second_fn = second_call.child_by_field_name("function")
        first_args = first_call.child_by_field_name("arguments")
        second_args = second_call.child_by_field_name("arguments")
        first_arg_ids = _identifiers(first_args) if first_args is not None else set()
        second_arg_ids = _identifiers(second_args) if second_args is not None else set()
        # Reordering/deletion is intentionally limited to independent, direct
        # call statements with disjoint argument data dependencies.
        if (first_fn is None or second_fn is None or
                first_fn.type != "identifier" or second_fn.type != "identifier" or
                first_arg_ids & second_arg_ids):
            continue
        # keep, swap adjacent calls, delete first call, duplicate first call
        targets.append(_target("call_sequence", STRUCTURAL, first, 4, 0, second=second))
    return targets


def _literal_dimension(code: str, node) -> Optional[int]:
    if node is None or node.type != "number_literal":
        return None
    try:
        value = int(_text(code, node), 0)
        return value if value > 0 else None
    except ValueError:
        return None


def _array_declarations(code: str, root) -> Dict[str, List[Optional[int]]]:
    result: Dict[str, List[Optional[int]]] = {}
    for node in _walk(root):
        if node.type != "array_declarator" or (
            node.parent is not None and node.parent.type == "array_declarator"
        ):
            continue
        dimensions = []
        current = node
        identifier = None
        while current is not None and current.type == "array_declarator":
            dimensions.append(_literal_dimension(code, current.child_by_field_name("size")))
            current = current.child_by_field_name("declarator")
        if current is not None and current.type == "identifier":
            identifier = _text(code, current)
        if identifier:
            result[identifier] = list(reversed(dimensions))
    return result


def _subscript_info(code: str, node, arrays: Dict[str, List[Optional[int]]]):
    depth = 1
    current = node.child_by_field_name("argument")
    while current is not None and current.type == "subscript_expression":
        depth += 1
        current = current.child_by_field_name("argument")
    if current is None or current.type != "identifier":
        return None, None, None
    dimensions = arrays.get(_text(code, current), [])
    bound = dimensions[depth - 1] if depth <= len(dimensions) else None
    inner_bound = dimensions[depth - 2] if depth > 1 and depth - 1 <= len(dimensions) else None
    return bound, inner_bound, current


def collect_mutation_targets(code: str, mutation_type: str = None,
                             mutation_kind: str = None) -> List[Dict]:
    """Collect factors once, in source order, with an explicit category."""
    tree = parser.parse(code.encode("utf-8"))
    with open("Step4_Mutation/Query_Mutation_Targets.scm", "r", encoding="utf-8") as f:
        captures = LANGUAGE.query(f.read()).captures(tree.root_node)

    captured_ranges = {
        (node.start_byte, node.end_byte, node.type) for node, _ in captures
    }
    arrays = _array_declarations(code, tree.root_node)
    targets: List[Dict] = []
    for node in _walk(tree.root_node):
        captured = (node.start_byte, node.end_byte, node.type) in captured_ranges

        if captured and node.type in {"assignment_expression", "binary_expression"}:
            operator = _operator_target(node)
            if operator is not None:
                targets.append(operator)
            comparison = _comparison_target(node)
            if comparison is not None:
                targets.append(comparison)

        if captured and node.type == "if_statement":
            choices = 3 if node.child_by_field_name("alternative") is not None else 1
            targets.append(_target("if", STRUCTURAL, node, choices, 0))
            condition = _condition_expression(node.child_by_field_name("condition"))
            if condition is not None and condition.type == "binary_expression":
                logical = next(
                    (child.type for child in condition.children if child.type in {"&&", "||"}),
                    None,
                )
                if logical:
                    targets.append(_target(
                        "condition_split", STRUCTURAL, node, 2, 0,
                        logical=logical, expression=condition,
                    ))

        if captured and node.type == "number_literal":
            in_for_condition = False
            parent = node.parent
            while parent is not None and parent.type != "function_definition":
                if parent.type == "for_statement":
                    condition = parent.child_by_field_name("condition")
                    in_for_condition = condition is not None and (
                        condition.start_byte <= node.start_byte < condition.end_byte
                    )
                    break
                parent = parent.parent
            literal_node = _integer_literal_node(code, node)
            if (not in_for_condition and literal_node is not None and
                    not _inside_array_dimension(node)):
                targets.append(_target("num_const", VALUE, literal_node, 7, 0))

        if captured and node.type == "subscript_expression":
            argument = node.child_by_field_name("argument")
            inner = argument if argument is not None and argument.type == "subscript_expression" else None
            bound, inner_bound, base = _subscript_info(code, node, arrays)
            targets.append(_target(
                "array_idx", VALUE, node, 4 if inner is not None else 3, 0,
                inner=inner, bound=bound, inner_bound=inner_bound, base=base,
            ))

        if captured and node.type == "for_statement":
            condition = node.child_by_field_name("condition")
            number = _integer_literal_node(code, _direct_number(condition))
            if number is not None:
                targets.append(_target("loop_bound", VALUE, number, 6, 0))
            body = node.child_by_field_name("body")
            update = node.child_by_field_name("update")
            if (condition is not None and update is not None and
                    body is not None and body.type == "compound_statement" and
                    not _contains(body, {"continue_statement", "goto_statement",
                                         "labeled_statement"})):
                targets.append(_target("loop_unroll", STRUCTURAL, node, 2, 0))

        if captured and node.type == "declaration":
            integer_type = _local_integer_declaration(code, node)
            if integer_type is not None:
                targets.append(integer_type)
            volatile = _volatile_target(code, node)
            if volatile is not None:
                targets.append(volatile)

        if node.type == "compound_statement":
            targets.extend(_call_sequence_targets(node))

    if mutation_type is not None:
        if mutation_type not in {VALUE, STRUCTURAL}:
            raise ValueError("mutation_type must be None, 'value', or 'structural'")
        targets = [target for target in targets if target["category"] == mutation_type]
    if mutation_kind is not None:
        targets = [target for target in targets if target["kind"] == mutation_kind]
    return targets


def vertex_info(code: str, mutation_type: str = None,
                mutation_kind: str = None) -> tuple:
    targets = collect_mutation_targets(code, mutation_type, mutation_kind)
    vertex_num = np.array([target["choices"] for target in targets])
    vertex_type = np.array([target["kind"] for target in targets])
    subgraph_type = np.array(["complete"] * len(targets))
    initial_vertex = np.array([target["initial"] for target in targets])
    return len(targets), vertex_num, vertex_type, subgraph_type, initial_vertex
