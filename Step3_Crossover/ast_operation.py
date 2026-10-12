import re
import random
import tree_sitter
from tree_sitter import Language, Parser
from Step3_Crossover.ast_information import (
    get_visible_declarations, split_declaration,
    get_node_context, get_node_roles, declaration_type_map,
)

parser = Parser()
parser.set_language(Language("Libs/tree_sitter/parser/my-languages.so", "c"))

_BLOCK_STATEMENT_TYPES = {
    "expression_statement",
    "if_statement",
    "for_statement",
    "while_statement",
    "do_statement",
    "switch_statement",
}
_UNSAFE_BLOCK_TRANSFERS = {
    "return_statement",
    "break_statement",
    "continue_statement",
    "goto_statement",
    "labeled_statement",
}

# 选择类型和结构用途均兼容的节点；同语义角色优先。
def select_nodes(ex_list_a: list, ex_list_b: list) -> tuple:
    while ex_list_a:
        node_a = random.choice(ex_list_a)
        context_a = get_node_context(node_a[1])
        roles_a = get_node_roles(node_a[1])
        same_type = [
            n for n in ex_list_b
            if n[1].type == node_a[1].type
            and get_node_context(n[1]) == context_a
        ]
        if same_type:
            weights = []
            for candidate in same_type:
                roles_b = get_node_roles(candidate[1])
                if roles_a == roles_b:
                    semantic_weight = 10.0
                elif roles_a & roles_b:
                    semantic_weight = 4.0
                else:
                    semantic_weight = 1.0
                weights.append(semantic_weight)
            node_b = random.choices(same_type, weights=weights, k=1)[0]
            return node_a, node_b
        ex_list_a.remove(node_a)
    return None, None


def get_statement_blocks(func_def: list) -> list:
    """Collect small executable blocks and retain their natural scopes."""
    blocks = []
    for func_index, function in enumerate(func_def):
        for compound in _walk(function):
            if compound.type != "compound_statement":
                continue
            statements = list(compound.named_children)
            for start in range(len(statements)):
                if statements[start].type not in _BLOCK_STATEMENT_TYPES:
                    continue
                for length in range(2, 5):
                    selected = statements[start:start + length]
                    if len(selected) != length:
                        break
                    if any(node.type not in _BLOCK_STATEMENT_TYPES for node in selected):
                        break
                    if any(
                        descendant.type in _UNSAFE_BLOCK_TRANSFERS
                        for node in selected
                        for descendant in _walk(node)
                    ):
                        continue
                    blocks.append((func_index, tuple(selected)))
    return blocks


def select_statement_blocks(blocks_a: list, blocks_b: list) -> tuple:
    """Match blocks by coarse control-flow shape and semantic roles."""
    while blocks_a:
        block_a = random.choice(blocks_a)
        nodes_a = block_a[1]
        roles_a = set().union(*(get_node_roles(node) for node in nodes_a))
        control_a = any(node.type != "expression_statement" for node in nodes_a)
        compatible = []
        weights = []
        for block_b in blocks_b:
            nodes_b = block_b[1]
            if abs(len(nodes_a) - len(nodes_b)) > 1:
                continue
            roles_b = set().union(*(get_node_roles(node) for node in nodes_b))
            control_b = any(
                node.type != "expression_statement" for node in nodes_b
            )
            if control_a != control_b and not (roles_a & roles_b):
                continue
            weight = 1.0
            if roles_a == roles_b:
                weight += 5.0
            elif roles_a & roles_b:
                weight += 2.0
            if control_a == control_b:
                weight += 2.0
            if len(nodes_a) == len(nodes_b):
                weight += 1.0
            compatible.append(block_b)
            weights.append(weight)
        if compatible:
            return block_a, random.choices(compatible, weights=weights, k=1)[0]
        blocks_a.remove(block_a)
    return None, None

# 获取变量和声明相关信息
def get_var_and_decl_info(root: tree_sitter.Node, global_node: list, select: tree_sitter.Node, code: str) -> tuple:
    visible = get_visible_declarations(root, global_node, select, code)
    return declaration_type_map(visible), visible

# 节点重命名
def rename_nodes(var_exist: dict, decl_new: list, select: tree_sitter.Node, code: str) -> tuple:
    return _rename_segment(
        var_exist, decl_new, select.start_byte, select.end_byte, code
    )


def rename_block(var_exist: dict, decl_new: list, block: tuple, code: str) -> tuple:
    return _rename_segment(
        var_exist, decl_new, block[0].start_byte, block[-1].end_byte, code
    )


def _rename_segment(var_exist: dict, decl_new: list, start_byte: int,
                    end_byte: int, code: str) -> tuple:
    reserved = {
        x.strip() for x in open(
            "Libs/tree_sitter/keywords/c.txt", "r", encoding="utf-8"
        ).readlines()
    }
    cross_segment = code.encode("utf-8")[start_byte:end_byte].decode(
        "utf-8", errors="replace"
    )
    split_decls = []
    for declaration in dict.fromkeys(decl_new):
        split_decls.extend(split_declaration(declaration))

    decl_types = declaration_type_map(split_decls)
    decl_map = {
        declaration: list(declaration_type_map([declaration]))
        for declaration in split_decls
    }
    segment_tree = parser.parse(cross_segment.encode("utf-8"))
    internal_names = set()
    for item in _walk(segment_tree.root_node):
        if item.type == "declaration":
            declaration = item.text.decode("utf-8", errors="replace")
            internal_names.update(declaration_type_map([declaration]))
    needed_names = {
        node.text.decode("utf-8", errors="replace")
        for node in _walk(segment_tree.root_node)
        if node.type == "identifier"
    }

    selected_decls = []
    changed = True
    while changed:
        changed = False
        for declaration, names in decl_map.items():
            if declaration in selected_decls or not (set(names) & needed_names):
                continue
            selected_decls.append(declaration)
            declaration_tree = parser.parse(declaration.encode("utf-8"))
            references = {
                node.text.decode("utf-8", errors="replace")
                for node in _walk(declaration_tree.root_node)
                if node.type == "identifier"
            } - set(names)
            old_size = len(needed_names)
            needed_names.update(references)
            changed = changed or len(needed_names) != old_size

    # Dependency discovery may find an earlier declaration in a later pass.
    # Restore source order so inserted initializers never precede dependencies.
    declaration_order = {declaration: index for index, declaration in enumerate(split_decls)}
    selected_decls.sort(key=lambda declaration: declaration_order[declaration])

    # Rename only incompatible collisions. Compatible destination variables can
    # be reused and their source declarations must not be reinserted.
    rename_map = {}
    used_names = set(var_exist) | reserved | needed_names
    count = 0
    reusable = set()
    for name in needed_names:
        if name in internal_names:
            continue
        if name not in decl_types or name not in var_exist:
            continue
        if decl_types[name] == var_exist[name]:
            reusable.add(name)
            continue
        while True:
            new_name = f"var_{count}"
            count += 1
            if new_name not in used_names:
                used_names.add(new_name)
                rename_map[name] = new_name
                break

    cross_segment = _rename_identifiers(cross_segment, rename_map)
    selected_decls = [
        _rename_identifiers(declaration, rename_map)
        for declaration in selected_decls
    ]

    declarations_to_insert = []
    for declaration in selected_decls:
        names = set(declaration_type_map([declaration]))
        if names and (names <= reusable or names <= internal_names):
            continue
        declarations_to_insert.append(declaration)
    return list(dict.fromkeys(declarations_to_insert)), cross_segment


def _walk(node: tree_sitter.Node):
    yield node
    for child in node.children:
        for descendant in _walk(child):
            yield descendant


def _rename_identifiers(source: str, rename_map: dict) -> str:
    """Rename C identifiers only; never alter comments or string literals."""
    if not rename_map:
        return source
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    edits = []
    for node in _walk(tree.root_node):
        if node.type != "identifier":
            continue
        name = source_bytes[node.start_byte:node.end_byte].decode(
            "utf-8", errors="replace"
        )
        replacement = rename_map.get(name)
        if replacement is not None:
            edits.append((node.start_byte, node.end_byte, replacement.encode("utf-8")))
    for start, end, replacement in sorted(edits, reverse=True):
        source_bytes = source_bytes[:start] + replacement + source_bytes[end:]
    return source_bytes.decode("utf-8")


def _function_name(func_def: tree_sitter.Node, code: str) -> str:
    declarator = func_def.child_by_field_name("declarator")
    if declarator is not None:
        for node in _walk(declarator):
            if node.type == "identifier":
                return code.encode("utf-8")[node.start_byte:node.end_byte].decode(
                    "utf-8", errors="replace"
                )
    return ""


def _compound_path(node: tree_sitter.Node,
                   func_def: tree_sitter.Node) -> list:
    """Return the named-child path from a function to node's scope."""
    path = []
    current = node.parent
    while current is not None and current != func_def:
        parent = current.parent
        if parent is None:
            return None
        index = next(
            (
                position for position, child in enumerate(parent.named_children)
                if child.start_byte == current.start_byte
                and child.end_byte == current.end_byte
                and child.type == current.type
            ),
            None,
        )
        if index is None:
            return None
        path.append(index)
        current = parent
    if current != func_def:
        return None
    return list(reversed(path))

def cross_nodes(code: str, select: tree_sitter.Node, func_def: tree_sitter.Node,
                segment: str, decl: list) -> str:
    return _cross_segment(
        code, select.start_byte, select.end_byte, func_def, segment, decl
    )


def cross_block(code: str, block: tuple, func_def: tree_sitter.Node,
                segment: str, decl: list) -> str:
    scope_path = _compound_path(block[0], func_def)
    return _cross_segment(
        code, block[0].start_byte, block[-1].end_byte, func_def, segment, decl,
        scope_path,
    )


def _cross_segment(code: str, start_byte: int, end_byte: int,
                   func_def: tree_sitter.Node, segment: str, decl: list,
                   scope_path: list = None) -> str:
    function_name = _function_name(func_def, code)
    code_bytes = code.encode("utf-8")
    code_bytes = (
        code_bytes[:start_byte] + segment.encode("utf-8") + code_bytes[end_byte:]
    )
    code = code_bytes.decode("utf-8")

    # step2: 在新代码上重新解析，找到 compound_statement 的正确插入位置
    new_tree = parser.parse(code.encode())
    new_root = new_tree.root_node

    target_func = None
    for child in new_root.children:
        if child.type == "function_definition":
            if _function_name(child, code) == function_name:
                target_func = child
                break
    if target_func is None:
        return code

    compound_stmt = target_func
    if scope_path is None:
        scope_path = []
        compound_stmt = next(
            (child for child in target_func.named_children
             if child.type == "compound_statement"),
            None,
        )
    else:
        for index in scope_path:
            children = compound_stmt.named_children
            if index >= len(children):
                return code
            compound_stmt = children[index]
    if compound_stmt is None or compound_stmt.type != "compound_statement":
        return code

    if not decl:
        return code
    insertion = ("\n" + "\n".join(decl) + "\n").encode("utf-8")
    code_bytes = code.encode("utf-8")
    insert_at = compound_stmt.start_byte + 1
    return (code_bytes[:insert_at] + insertion + code_bytes[insert_at:]).decode("utf-8")
