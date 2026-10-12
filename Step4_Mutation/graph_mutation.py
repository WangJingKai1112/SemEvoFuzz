from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

from Step4_Mutation.graph_information import (
    ARITHMETIC,
    COMPARISONS,
    INTEGER_TYPES,
    collect_mutation_targets,
)
from Utils.file_utils import write_log


LOG_PATH = "log.txt"


class graphInfo:
    def __init__(self, factors: int, vertex_num: np.array, vertex_type: np.array,
                 subgraph_type: np.array, initial_vertex: np.array):
        assert factors == len(vertex_num)
        self.factors = factors
        self.vertex_num = vertex_num
        self.vertex_type = vertex_type
        self.suggest_init = torch.Tensor(initial_vertex).long().unsqueeze(0)
        self.adjacency_matrix = []
        self.fourier_freq = []
        self.fourier_basis = []

        for index, vertex in enumerate(self.vertex_num):
            if subgraph_type[index] == "path":
                adjacency = (
                    torch.diag(torch.ones(vertex - 1), -1) +
                    torch.diag(torch.ones(vertex - 1), 1)
                )
            else:
                adjacency = torch.ones(vertex, vertex) - torch.eye(vertex)
            adjacency *= max(vertex - 1.0, 1.0)
            self.adjacency_matrix.append(adjacency)
            degree = torch.sum(adjacency, dim=0)
            laplacian = torch.diag(degree) - adjacency
            eigenvalues, eigenvectors = torch.linalg.eigh(laplacian)
            self.fourier_freq.append(eigenvalues)
            self.fourier_basis.append(eigenvectors)


def _bytes(code: str, node) -> bytes:
    return code.encode("utf-8")[node.start_byte:node.end_byte]


def _text(code: str, node) -> str:
    return _bytes(code, node).decode("utf-8", errors="replace")


def _replace(code: str, start: int, end: int, replacement: str) -> str:
    source = code.encode("utf-8")
    return (source[:start] + replacement.encode("utf-8") + source[end:]).decode("utf-8")


def _parse_integer_literal(text: str) -> Optional[Tuple[int, str]]:
    match = __import__("re").fullmatch(
        r"\s*([+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]*|[0-9]+))([uUlL]*)\s*",
        text,
    )
    if not match:
        return None
    literal, suffix = match.groups()
    sign = -1 if literal.startswith("-") else 1
    unsigned_literal = literal.lstrip("+-")
    if unsigned_literal.lower().startswith("0x"):
        base = 16
    elif unsigned_literal.lower().startswith("0b"):
        base = 2
    elif len(unsigned_literal) > 1 and unsigned_literal.startswith("0"):
        base = 8
    else:
        base = 10
    return sign * int(unsigned_literal, base), suffix


def _integer_replacement(code: str, node, choice: int, loop_bound: bool = False) -> str:
    parsed = _parse_integer_literal(_text(code, node))
    if parsed is None:
        return _text(code, node)
    value, suffix = parsed
    if loop_bound:
        candidates = [value, value + 1, value - 1, value + 2, value - 2, value * 2]
    else:
        candidates = [value, value + 1, value - 1, value * 2, 0, 1, -value]
    new_value = candidates[choice]
    if suffix.lower().startswith("u") and new_value < 0:
        new_value = 0
    return f"{new_value}{suffix}"


def _index_node(node):
    index = node.child_by_field_name("index")
    if index is not None:
        return index
    named = list(node.named_children)
    return named[-1] if named else None


def _bounded_index(expression: str, bound: int, delta: int = 0) -> str:
    """Normalize an integer expression into [0, bound) using C arithmetic."""
    normalized = f"((({expression}) % {bound} + {bound}) % {bound})"
    return f"(({normalized} + ({delta}) + {bound}) % {bound})"


def _body_contents(code: str, body) -> str:
    text = _text(code, body)
    if body.type == "compound_statement" and text.startswith("{") and text.endswith("}"):
        return text[1:-1].strip()
    return text


def _if_replacement(code: str, target: Dict, choice: int) -> Optional[str]:
    node = target["node"]
    if choice == 0:
        return None
    consequence = node.child_by_field_name("consequence")
    alternative = node.child_by_field_name("alternative")
    if consequence is None or alternative is None:
        return None
    if choice == 1:
        return _text(code, node)[:consequence.end_byte - node.start_byte]
    alternative_text = _text(code, alternative)
    if alternative_text.lstrip().startswith("else"):
        alternative_text = alternative_text.lstrip()[4:].lstrip()
    return alternative_text


def _split_condition(code: str, target: Dict, choice: int) -> Optional[str]:
    if choice == 0:
        return None
    node = target["node"]
    condition = target.get("expression")
    consequence = node.child_by_field_name("consequence")
    alternative = node.child_by_field_name("alternative")
    left = condition.child_by_field_name("left") if condition is not None else None
    right = condition.child_by_field_name("right") if condition is not None else None
    if left is None or right is None or consequence is None:
        return None
    left_text, right_text = _text(code, left), _text(code, right)
    body = _text(code, consequence)
    else_text = ""
    if alternative is not None:
        alternative_text = _text(code, alternative).lstrip()
        if alternative_text.startswith("else"):
            alternative_text = alternative_text[4:].lstrip()
        else_text = f" else {alternative_text}"
    if target["logical"] == "&&":
        inner = f"if ({right_text}) {body}{else_text}"
        outer_else = else_text
        return f"if ({left_text}) {{ {inner} }}{outer_else}"
    # a || b is split without duplicating evaluation of either operand.
    return f"if ({left_text}) {body} else if ({right_text}) {body}{else_text}"


def _loop_unroll(code: str, target: Dict, choice: int) -> Optional[str]:
    if choice == 0:
        return None
    node = target["node"]
    initializer = node.child_by_field_name("initializer")
    condition = node.child_by_field_name("condition")
    update = node.child_by_field_name("update")
    body = node.child_by_field_name("body")
    if condition is None or update is None or body is None:
        return None
    init_text = _text(code, initializer).strip() if initializer is not None else ""
    if init_text and not init_text.endswith(";"):
        init_text += ";"
    body_text = _body_contents(code, body)
    update_text = _text(code, update).strip().rstrip(";")
    # Factor-two unrolling preserves the original guard before the copied body.
    return (
        f"for ({init_text} {_text(code, condition)}; {update_text}) {{\n"
        f"{{\n{body_text}\n}}\n{update_text};\n"
        f"if (!({_text(code, condition)})) break;\n"
        f"{{\n{body_text}\n}}\n"
        f"}}"
    )


def _call_sequence(code: str, target: Dict, choice: int) -> Optional[str]:
    if choice == 0:
        return None
    first, second = target["node"], target["second"]
    first_text, second_text = _text(code, first), _text(code, second)
    separator = code.encode("utf-8")[first.end_byte:second.start_byte].decode(
        "utf-8", errors="replace"
    )
    if choice == 1:
        return second_text + separator + first_text
    if choice == 2:
        return second_text
    return first_text + separator + first_text + separator + second_text


def _edit_for_target(code: str, target: Dict, choice: int):
    node = target["node"]
    kind = target["kind"]
    if choice == target["initial"]:
        return None
    if kind == "op":
        return node.start_byte, node.end_byte, ARITHMETIC[choice]
    if kind == "compare":
        return node.start_byte, node.end_byte, COMPARISONS[choice]
    if kind == "num_const":
        return node.start_byte, node.end_byte, _integer_replacement(code, node, choice)
    if kind == "loop_bound":
        return node.start_byte, node.end_byte, _integer_replacement(code, node, choice, True)
    if kind == "array_idx":
        index = _index_node(node)
        if index is None:
            return None
        index_text = _text(code, index)
        bound = target.get("bound")
        if choice == 1:
            replacement = (
                _bounded_index(index_text, bound, 1)
                if bound is not None else f"(({index_text}) + 1)"
            )
        elif choice == 2:
            replacement = (
                _bounded_index(index_text, bound, -1)
                if bound is not None
                else f"(({index_text}) > 0 ? ({index_text}) - 1 : 0)"
            )
        else:
            inner = target.get("inner")
            inner_index = _index_node(inner) if inner is not None else None
            base = target.get("base")
            if inner_index is None or base is None:
                return None
            outer_text = _text(code, index)
            inner_text = _text(code, inner_index)
            outer_bound = target.get("bound")
            inner_bound = target.get("inner_bound")
            first_index = (
                _bounded_index(outer_text, inner_bound) if inner_bound is not None
                else outer_text
            )
            second_index = (
                _bounded_index(inner_text, outer_bound) if outer_bound is not None
                else inner_text
            )
            replacement = (
                f"{_text(code, base)}[{first_index}]"
                f"[{second_index}]"
            )
            return node.start_byte, node.end_byte, replacement
        return index.start_byte, index.end_byte, replacement
    if kind == "integer_type":
        return node.start_byte, node.end_byte, INTEGER_TYPES[choice]
    if kind == "volatile":
        qualifier = target.get("qualifier")
        if choice == 1 and qualifier is None:
            return node.start_byte, node.start_byte, "volatile "
        if choice == 0 and qualifier is not None:
            end = qualifier.end_byte
            source = code.encode("utf-8")
            while end < len(source) and source[end:end + 1].isspace():
                end += 1
            return qualifier.start_byte, end, ""
        return None
    if kind == "if":
        replacement = _if_replacement(code, target, choice)
    elif kind == "condition_split":
        replacement = _split_condition(code, target, choice)
    elif kind == "loop_unroll":
        replacement = _loop_unroll(code, target, choice)
    elif kind == "call_sequence":
        replacement = _call_sequence(code, target, choice)
        if replacement is not None:
            return node.start_byte, target["second"].end_byte, replacement
    else:
        replacement = None
    if replacement is None:
        return None
    return node.start_byte, node.end_byte, replacement


class graphMutaton:
    """Apply a graph suggestion to the exact factor list used to build it."""

    def __init__(self, code: str, tree, vertex_num: np.array, vertex_type: np.array,
                 eval_input: torch.Tensor, mutation_type: str = None,
                 mutation_kind: str = None):
        self.code = code
        self.tree = tree
        self.vertex_num = vertex_num
        self.vertex_type = vertex_type
        self.eval_input = eval_input
        self.mutation_type = mutation_type
        self.mutation_kind = mutation_kind
        self.high_risk_applied = False

    def mutate(self, node=None) -> str:
        targets = collect_mutation_targets(
            self.code, self.mutation_type, self.mutation_kind
        )
        if len(targets) != len(self.eval_input):
            write_log(LOG_PATH, "[WARN] mutation target/vector length mismatch\n")
            self.code = ""
            return self.code

        edits = []
        for index, target in enumerate(targets):
            choice = int(self.eval_input[index])
            if choice >= target["choices"]:
                self.code = ""
                return self.code
            edit = _edit_for_target(self.code, target, choice)
            if edit is not None:
                edits.append((edit[0], edit[1], edit[2], target["kind"]))

        # When two selected structural factors overlap, keep the outermost edit.
        selected = []
        for edit in sorted(edits, key=lambda item: (item[0], -(item[1] - item[0]))):
            if any(not (edit[1] <= current[0] or edit[0] >= current[1]) for current in selected):
                continue
            selected.append(edit)
        for start, end, replacement, kind in sorted(selected, reverse=True):
            self.code = _replace(self.code, start, end, replacement)
            if kind in {"loop_unroll", "condition_split"}:
                self.high_risk_applied = True
        return self.code
