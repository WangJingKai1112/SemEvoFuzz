import re
import tree_sitter
from tree_sitter import Language, Parser
from typing import Dict, List, Set

LANGUAGE = Language("Libs/tree_sitter/parser/my-languages.so", "c")
parser = Parser()
parser.set_language(LANGUAGE)
_semantic_query = None

# 提取函数定义和全局变量
def extract_func_and_decl(node: tree_sitter.Node) -> tuple:
    func_def, global_decl = [], []
    for child in node.children:
        if child.type == "function_definition":
            func_def.append(child)
        if child.type == "declaration":
            global_decl.append(child)
    return func_def, global_decl

# 获取可交换列表
def get_swap_list(func_def: list) -> list:
    swap_list = []
    with open("Step3_Crossover/Query_Swap_List.scm", "r") as f:
        query_text = f.read()
    query = LANGUAGE.query(query_text)
    for i in range(len(func_def)):
        node = func_def[i]
        captures = query.captures(node)
        for n, _ in captures:
            swap_list.append((i, n))
    return swap_list

# 获取变量名
def get_var_name(node: tree_sitter.Node, code: str) -> list:
    var_name = []
    with open("Step3_Crossover/Query_Var_Name.scm", "r") as f:
        query_text = f.read()
    query = LANGUAGE.query(query_text)
    captures = query.captures(node)
    source = code.encode("utf-8")
    for n, _ in captures:
        var_name.append((
            n.start_point,
            source[n.start_byte:n.end_byte].decode("utf-8", errors="replace"),
        ))
    return var_name

# 获取声明语句
def get_declaration(node: tree_sitter.Node, code: str) -> list:
    declaration = []
    query_text_1 = LANGUAGE.query("(declaration) @declaration1")
    query_text_2 = LANGUAGE.query("(parameter_declaration) @declaration2")
    captures_1 = query_text_1.captures(node)
    captures_2 = query_text_2.captures(node)
    source = code.encode("utf-8")
    for n, _ in captures_1:
        declaration.append(
            source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
        )
    for n, _ in captures_2:
        text = source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
        if text == "void":
            continue
        declaration.append(text + ";")
    return declaration


def _contains_node(container: tree_sitter.Node, node: tree_sitter.Node) -> bool:
    return (
        container.start_byte <= node.start_byte and
        node.end_byte <= container.end_byte
    )


def get_visible_declarations(func_def: tree_sitter.Node, global_nodes: list,
                             select: tree_sitter.Node, code: str) -> list:
    """Return declarations that are in scope at a crossover location."""
    visible = []

    # Only file-scope declarations preceding this function are visible in C.
    for node in global_nodes:
        if node.end_byte <= func_def.start_byte:
            visible.append(
                code.encode("utf-8")[node.start_byte:node.end_byte].decode(
                    "utf-8", errors="replace"
                )
            )

    source = code.encode("utf-8")
    parameter_query = LANGUAGE.query("(parameter_declaration) @parameter")
    declarator = func_def.child_by_field_name("declarator")
    parameter_captures = (
        parameter_query.captures(declarator) if declarator is not None else []
    )
    for node, _ in parameter_captures:
        text = source[node.start_byte:node.end_byte].decode(
            "utf-8", errors="replace"
        )
        if text.strip() != "void":
            visible.append(text + ";")

    declaration_query = LANGUAGE.query("(declaration) @declaration")
    for declaration, _ in declaration_query.captures(func_def):
        if declaration.end_byte > select.start_byte:
            continue

        # The nearest compound scope must contain the selected node.
        scope = declaration.parent
        while scope is not None and scope != func_def and scope.type != "compound_statement":
            scope = scope.parent
        if scope is None or scope == func_def or not _contains_node(scope, select):
            continue

        # A declaration in a for initializer is visible only inside that loop.
        ancestor = declaration.parent
        in_scope = True
        while ancestor is not None and ancestor != scope:
            if ancestor.type == "for_statement" and not _contains_node(ancestor, select):
                in_scope = False
                break
            ancestor = ancestor.parent
        if in_scope:
            text = source[declaration.start_byte:declaration.end_byte].decode(
                "utf-8", errors="replace"
            )
            visible.append(text)

    return list(dict.fromkeys(visible))

# 提取声明语句中的变量名
def extract_decl_name(decl_stmt: str) -> list:
    pattern = r"\b[a-zA-Z_]\w*\b(?=\s*(?:=|,|;|\[|&|\}))"
    decl_name = []
    unique_name = set()
    matches = re.findall(pattern, decl_stmt)
    for var in matches:
        if var and var.strip() not in unique_name:
            decl_name.append(var.strip())
            unique_name.add(var.strip())
    return decl_name

# 拆分声明语句
def split_declaration(decl_stmt: str) -> list:
    source_text = decl_stmt if decl_stmt.rstrip().endswith(";") else decl_stmt + ";"
    source = source_text.encode("utf-8")
    tree = parser.parse(source)
    declaration = next(
        (node for node in tree.root_node.named_children if node.type == "declaration"),
        None,
    )
    if declaration is None:
        return [decl_stmt]

    declarator_types = {
        "init_declarator", "identifier", "pointer_declarator",
        "array_declarator", "function_declarator", "parenthesized_declarator",
    }
    declarators = [
        child for child in declaration.named_children
        if child.type in declarator_types
    ]
    if len(declarators) <= 1:
        return [source_text]

    prefix = source[declaration.start_byte:declarators[0].start_byte]
    return [
        (prefix + source[node.start_byte:node.end_byte] + b";").decode(
            "utf-8", errors="replace"
        )
        for node in declarators
    ]


def _node_text(node: tree_sitter.Node) -> str:
    value = node.text
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _walk(node: tree_sitter.Node):
    yield node
    for child in node.children:
        for descendant in _walk(child):
            yield descendant


def _identifiers(node: tree_sitter.Node) -> Set[str]:
    return {_node_text(item) for item in _walk(node) if item.type == "identifier"}


def _expression_root(node: tree_sitter.Node) -> tree_sitter.Node:
    """Ignore parentheses when identifying a control expression's root."""
    while node.type == "parenthesized_expression" and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _condition_position(expression: tree_sitter.Node,
                        node: tree_sitter.Node) -> str:
    position = "root" if node == _expression_root(expression) else "nested"
    if node.type != "binary_expression":
        return position

    operator = next((child.type for child in node.children if child.type in {
        "==", "!=", "<", "<=", ">", ">=", "&&", "||",
        "+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>",
    }), None)
    if operator in {"==", "!=", "<", "<=", ">", ">="}:
        kind = "comparison"
    elif operator in {"&&", "||"}:
        kind = "logical"
    elif operator in {"+", "-", "*", "/", "%"}:
        kind = "arithmetic"
    elif operator in {"&", "|", "^", "<<", ">>"}:
        kind = "bitwise"
    else:
        kind = "other"
    return f"{position}_{kind}"


def _modified_identifiers(node: tree_sitter.Node) -> Set[str]:
    modified = set()
    for candidate in _walk(node):
        if candidate.type == "assignment_expression":
            left = candidate.child_by_field_name("left")
            if left is not None:
                modified.update(_identifiers(left))
        elif candidate.type == "update_expression":
            modified.update(_identifiers(candidate))
    return modified


def _loop_control_signature(statement: tree_sitter.Node) -> str:
    condition = statement.child_by_field_name("condition")
    condition_ids = _identifiers(condition) if condition is not None else set()

    if statement.type == "for_statement":
        initializer = statement.child_by_field_name("initializer")
        update = statement.child_by_field_name("update")
        initializer_ids = (
            _identifiers(initializer) if initializer is not None else set()
        )
        update_ids = (
            _modified_identifiers(update) if update is not None else set()
        )
        control_ids = condition_ids & update_ids
        if initializer_ids:
            control_ids &= initializer_ids
        if not control_ids:
            control_ids = ((condition_ids & update_ids) or
                           (initializer_ids & condition_ids) or
                           (initializer_ids & update_ids))
    else:
        body = statement.child_by_field_name("body")
        modified_ids = _modified_identifiers(body) if body is not None else set()
        control_ids = condition_ids & modified_ids

    if not control_ids:
        control_ids = condition_ids
    return ",".join(sorted(control_ids)) or "none"


def get_node_context(node: tree_sitter.Node) -> str:
    """Return the nearest structural use of a crossover candidate."""
    current = node
    while current.parent is not None:
        parent = current.parent

        if parent.type == "subscript_expression":
            index = parent.child_by_field_name("index")
            if index is None and parent.named_children:
                index = parent.named_children[-1]
            if index is not None and _contains_node(index, node):
                position = "root" if node == _expression_root(index) else "nested"
                return f"array_index_{position}"

        if parent.type == "assignment_expression":
            for field in ("left", "right"):
                expression = parent.child_by_field_name(field)
                if expression is not None and _contains_node(expression, node):
                    position = "root" if node == _expression_root(expression) else "nested"
                    return f"assignment_{field}_{position}"

        if parent.type == "for_statement":
            control = _loop_control_signature(parent)
            for field in ("initializer", "condition", "update"):
                expression = parent.child_by_field_name(field)
                if expression is not None and _contains_node(expression, node):
                    if field == "condition":
                        position = _condition_position(expression, node)
                        return f"for_condition_{position}:{control}"
                    position = "root" if node == _expression_root(expression) else "nested"
                    return f"for_{field}_{position}:{control}"

        if parent.type in {"while_statement", "do_statement"}:
            condition = parent.child_by_field_name("condition")
            if condition is not None and _contains_node(condition, node):
                position = _condition_position(condition, node)
                control = _loop_control_signature(parent)
                return f"{parent.type}_condition_{position}:{control}"

        if parent.type in {"if_statement", "switch_statement"}:
            condition = parent.child_by_field_name("condition")
            if condition is not None and _contains_node(condition, node):
                position = _condition_position(condition, node)
                return f"{parent.type}_condition_{position}"

        if parent.type == "return_statement":
            expression = next(iter(parent.named_children), None)
            if expression is not None and _contains_node(expression, node):
                position = "root" if node == _expression_root(expression) else "nested"
                return f"return_expression_{position}"

        current = parent

    return "generic_expression"


def get_node_roles(node: tree_sitter.Node) -> Set[str]:
    """Return the variable-semantic roles represented by a swap candidate."""
    context_root = node
    while context_root.parent is not None and context_root.type != "function_definition":
        context_root = context_root.parent
    global _semantic_query
    if _semantic_query is None:
        query_path = "Step3_Crossover/Query_Semantic_Role.scm"
        with open(query_path, "r", encoding="utf-8") as query_file:
            _semantic_query = LANGUAGE.query(query_file.read())

    node_identifiers = _identifiers(node)
    variables_by_role: Dict[str, Set[str]] = {
        "loop_control": set(),
        "accumulator": set(),
        "condition": set(),
        "array_index": set(),
        "return_related": set(),
    }
    for captured, capture_name in _semantic_query.captures(context_root):
        if capture_name in {"loop_control", "condition", "array_index", "return_related"}:
            variables_by_role[capture_name].update(_identifiers(captured))

    # Accumulator: x = x + ..., x += ..., x++, and x--.
    for candidate in _walk(context_root):
        if candidate.type == "assignment_expression":
            left = candidate.child_by_field_name("left")
            right = candidate.child_by_field_name("right")
            operator = next(
                (child.type for child in candidate.children
                 if child.type in {"=", "+=", "-=", "*=", "/=", "%="}),
                None,
            )
            left_ids = _identifiers(left) if left is not None else set()
            right_ids = _identifiers(right) if right is not None else set()
            if operator in {"+=", "-=", "*=", "/=", "%="} or left_ids & right_ids:
                variables_by_role["accumulator"].update(left_ids)
        elif candidate.type == "update_expression":
            variables_by_role["accumulator"].update(_identifiers(candidate))

    roles = {
        role for role, variables in variables_by_role.items()
        if node_identifiers & variables
    }

    return roles or {"generic"}


def get_node_role(node: tree_sitter.Node) -> str:
    """Backward-compatible, deterministic representation of all node roles."""
    return "+".join(sorted(get_node_roles(node)))


def declaration_type_map(declarations: List[str]) -> Dict[str, str]:
    """Extract a conservative C type signature for every declared symbol."""
    result: Dict[str, str] = {}
    for declaration in declarations:
        source = declaration if declaration.rstrip().endswith(";") else declaration + ";"
        tree = parser.parse(source.encode("utf-8"))
        declaration_node = next(
            (item for item in _walk(tree.root_node)
             if item.type in {"declaration", "parameter_declaration"}),
            None,
        )
        if declaration_node is None:
            continue
        base_parts = []
        for child in declaration_node.named_children:
            if child.type in {
                "primitive_type", "type_identifier", "sized_type_specifier",
                "struct_specifier", "union_specifier", "enum_specifier",
                "type_qualifier", "storage_class_specifier",
            }:
                base_parts.append(_node_text(child))
        base = " ".join(base_parts).strip()
        declarators = []
        for child in declaration_node.named_children:
            if child.type == "init_declarator":
                declarator = child.child_by_field_name("declarator")
                if declarator is not None:
                    declarators.append(declarator)
            elif child.type in {
                "identifier", "pointer_declarator", "array_declarator",
                "function_declarator", "parenthesized_declarator",
            }:
                declarators.append(child)

        for declarator in declarators:
            identifier = next(
                (item for item in _walk(declarator) if item.type == "identifier"),
                None,
            )
            if identifier is None:
                continue
            parent = identifier.parent
            shape = []
            while parent is not None and parent != declaration_node:
                if parent.type == "pointer_declarator":
                    shape.append("*")
                elif parent.type == "array_declarator":
                    size = parent.child_by_field_name("size")
                    shape.append("[" + (_node_text(size) if size is not None else "") + "]")
                elif parent.type == "function_declarator":
                    shape.append("()")
                parent = parent.parent
            result[_node_text(identifier)] = re.sub(
                r"\s+", " ", base + " " + "".join(reversed(shape))
            ).strip()
    return result


def _runtime_declarators(node):
    """Yield the simple declarators contained in one C declaration."""
    declarator_types = {
        "init_declarator", "identifier", "pointer_declarator",
        "array_declarator", "function_declarator", "parenthesized_declarator",
    }
    return [child for child in node.named_children
            if child.type in declarator_types]


def _runtime_declarator_info(node):
    """Return (name, is_array, is_pointer, initializer) for a declarator."""
    initializer = None
    declarator = node
    if node.type == "init_declarator":
        declarator = node.child_by_field_name("declarator")
        initializer = node.child_by_field_name("value")
        if initializer is None:
            initializer = node.child_by_field_name("initializer")
    if declarator is None:
        return None

    identifier = next(
        (item for item in _walk(declarator) if item.type == "identifier"),
        None,
    )
    if identifier is None:
        return None
    is_array = any(item.type == "array_declarator" for item in _walk(declarator))
    is_pointer = any(item.type in {"pointer_declarator", "function_declarator"}
                     for item in _walk(declarator))
    return _node_text(identifier), is_array, is_pointer, initializer


def _runtime_symbol_names(declaration):
    names = []
    for declarator in _runtime_declarators(declaration):
        info = _runtime_declarator_info(declarator)
        if info is not None:
            names.append(info)
    return names


def has_uninitialized_reads(code: str) -> bool:
    """Reject only definite local uninitialized reads introduced by operators.

    This is intentionally a small AST data-flow check.  It covers scalar/pointer
    reads and array subscripts whose first element access precedes every write,
    while leaving complex aliasing and uncertain control-flow untouched.
    """
    tree = parser.parse(code.encode("utf-8"))
    root = tree.root_node

    global_symbols = {}
    for declaration in root.named_children:
        if declaration.type != "declaration":
            continue
        for name, is_array, is_pointer, _ in _runtime_symbol_names(declaration):
            global_symbols[name] = {
                "array": is_array,
                "pointer": is_pointer,
                "initialized": True,
                "written": True,
                "partial": False,
                "written_indices": set(),
                "writes_unknown_index": False,
            }

    def first_identifier(node):
        return next((item for item in _walk(node) if item.type == "identifier"), None)

    def parameter_names(function):
        declarator = function.child_by_field_name("declarator")
        if declarator is None:
            return set()
        return {
            _node_text(identifier)
            for parameter in _walk(declarator)
            if parameter.type == "parameter_declaration"
            for identifier in [first_identifier(parameter)]
            if identifier is not None
        }

    def function_body(function):
        body = function.child_by_field_name("body")
        if body is not None:
            return body
        return next((item for item in function.named_children
                     if item.type == "compound_statement"), None)

    for function in (item for item in root.named_children
                     if item.type == "function_definition"):
        body = function_body(function)
        if body is None:
            continue

        symbols = {
            name: {
                **info,
                "written_indices": set(info["written_indices"]),
            }
            for name, info in global_symbols.items()
        }
        for name in parameter_names(function):
            symbols[name] = {
                "array": False,
                "pointer": False,
                "initialized": True,
                "written": True,
                "partial": False,
                "written_indices": set(),
                "writes_unknown_index": False,
            }

        declarations = [
            item for item in _walk(body) if item.type == "declaration"
        ]
        for declaration in declarations:
            for name, is_array, is_pointer, initializer in _runtime_symbol_names(declaration):
                symbols[name] = {
                    "array": is_array,
                    "pointer": is_pointer,
                    "initialized": False,
                    "written": False,
                    "partial": False,
                    "written_indices": set(),
                    "writes_unknown_index": False,
                }

        def assignment_array_names(node):
            names = []
            for candidate in _walk(node):
                if candidate.type != "assignment_expression":
                    continue
                left = candidate.child_by_field_name("left")
                if left is None or left.type != "subscript_expression":
                    continue
                base = left.child_by_field_name("argument")
                if base is None and left.named_children:
                    base = left.named_children[0]
                if base is not None and base.type == "identifier":
                    names.append(_node_text(base))
            return names

        # A loop that advances its control variable before the first write to
        # an array can leave the initial element undefined (the shape produced
        # by the expanded-loop operator).  Track only this narrow pattern.
        for loop in (item for item in _walk(body) if item.type == "for_statement"):
            loop_body = loop.child_by_field_name("body")
            if loop_body is None or loop_body.type != "compound_statement":
                continue
            seen = set()
            advanced = False
            for statement in loop_body.named_children:
                for name in assignment_array_names(statement):
                    if name in symbols and symbols[name]["array"]:
                        if advanced and name not in seen:
                            symbols[name]["partial"] = True
                        seen.add(name)
                if any(item.type == "update_expression" for item in _walk(statement)):
                    advanced = True

        invalid = False

        def read_identifier(node):
            nonlocal invalid
            name = _node_text(node)
            symbol = symbols.get(name)
            if symbol is None or symbol["initialized"]:
                return
            if symbol["array"] and not symbol["pointer"]:
                return
            invalid = True

        def subscript_parts(node):
            base = node.child_by_field_name("argument")
            index = node.child_by_field_name("index")
            named = list(node.named_children)
            if base is None and named:
                base = named[0]
            if index is None and len(named) > 1:
                index = named[-1]
            return base, index

        def literal_index(index):
            if index is None:
                return None
            if index.type == "number_literal":
                return _node_text(index).strip()
            return None

        def process(node):
            nonlocal invalid
            if invalid or node is None:
                return
            if node.type == "declaration":
                for declarator in _runtime_declarators(node):
                    info = _runtime_declarator_info(declarator)
                    if info is None:
                        continue
                    name, is_array, is_pointer, initializer = info
                    target = symbols.get(name)
                    if target is None:
                        continue
                    # Array dimensions and initializer expressions are reads.
                    declaration_node = declarator
                    for item in _walk(declaration_node):
                        if item.type == "array_declarator":
                            size = item.child_by_field_name("size")
                            if size is not None:
                                process(size)
                    if initializer is not None:
                        process(initializer)
                        target["initialized"] = True
                        target["written"] = True
                return
            if node.type == "assignment_expression":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                operator = next(
                    (child.type for child in node.children
                     if child.type in {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="}),
                    "=",
                )
                if operator != "=":
                    process(left)
                elif left is not None and left.type == "subscript_expression":
                    _, index = subscript_parts(left)
                    process(index)
                if right is not None:
                    process(right)
                if left is not None:
                    target = left
                    while target.type == "parenthesized_expression" and target.named_children:
                        target = target.named_children[0]
                    if target.type == "identifier":
                        symbol = symbols.get(_node_text(target))
                        if symbol is not None:
                            symbol["initialized"] = True
                            symbol["written"] = True
                    elif target.type == "subscript_expression":
                        base, index = subscript_parts(target)
                        if base is not None and base.type == "identifier":
                            symbol = symbols.get(_node_text(base))
                            if symbol is not None:
                                symbol["written"] = True
                                index_text = literal_index(index)
                                if index_text is not None:
                                    symbol["written_indices"].add(index_text)
                                else:
                                    symbol["writes_unknown_index"] = True
                return
            if node.type == "update_expression":
                for child in node.named_children:
                    process(child)
                target = next(iter(node.named_children), None)
                if target is not None:
                    while target.type == "parenthesized_expression" and target.named_children:
                        target = target.named_children[0]
                    if target.type == "identifier":
                        symbol = symbols.get(_node_text(target))
                        if symbol is not None:
                            symbol["initialized"] = True
                            symbol["written"] = True
                return
            if node.type == "subscript_expression":
                base, index = subscript_parts(node)
                process(index)
                if base is not None and base.type == "identifier":
                    symbol = symbols.get(_node_text(base))
                    if symbol is not None:
                        if symbol["pointer"] and not symbol["initialized"]:
                            invalid = True
                        elif symbol["array"]:
                            index_text = literal_index(index)
                            if (symbol["partial"] or not symbol["written"] or
                                    (index_text is not None and
                                     not symbol["writes_unknown_index"] and
                                     index_text not in symbol["written_indices"])):
                                invalid = True
                        return
                process(base)
                return
            if node.type == "call_expression":
                function_node = node.child_by_field_name("function")
                if function_node is not None and function_node.type != "identifier":
                    process(function_node)
                arguments = node.child_by_field_name("arguments")
                if arguments is not None:
                    for argument in arguments.named_children:
                        if argument.type != "identifier":
                            continue
                        symbol = symbols.get(_node_text(argument))
                        if symbol is not None and symbol["array"] and symbol["partial"]:
                            invalid = True
                            return
                    process(arguments)
                return
            if node.type == "sizeof_expression":
                return
            if node.type == "identifier":
                parent = node.parent
                if parent is not None and parent.type == "field_expression":
                    field = parent.child_by_field_name("field")
                    if field == node:
                        return
                read_identifier(node)
                return
            for child in node.named_children:
                process(child)

        process(body)
        if invalid:
            return True
    return False
