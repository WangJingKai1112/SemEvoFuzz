import numpy as np
from tree_sitter import Language, Parser

LANGUAGE = Language('../../Libs/tree_sitter/parser/my-languages.so', 'c')
parser = Parser()
parser.set_language(LANGUAGE)

def NodeCounter(
        cursor,
        code,
        n_factors,
        n_vertices_num,
        n_vertices_type,
        subgraph_type,
        init_vertex
    ):
    node = cursor.node
    op = ['+', '-', '*', '/']
    compare = ['>', '<', '>=', '<=', '==', '!=']

    if node.type == 'assignment_expression' or node.type == 'binary_expression':
        for child in node.children:
            if child.type in op:
                n_factors += 1
                n_vertices_num.append(4)
                n_vertices_type.append('op')
                subgraph_type.append('complete')
                init_vertex.append(op.index(child.type))

    elif node.type in compare:
        n_factors += 1
        n_vertices_num.append(6)
        n_vertices_type.append('compare')
        subgraph_type.append('complete')
        init_vertex.append(compare.index(node.type))

    elif node.type == 'if_statement':
        n_factors += 1
        n_vertices_num.append(3 if len(node.named_children) > 2 else 1)
        n_vertices_type.append('if')
        subgraph_type.append('complete')
        init_vertex.append(0)

    if cursor.goto_first_child():
        while True:
            n_factors, n_vertices_num, n_vertices_type, subgraph_type, init_vertex = NodeCounter(
                cursor = cursor,
                code = code,
                n_factors = n_factors,
                n_vertices_num = n_vertices_num,
                n_vertices_type = n_vertices_type,
                subgraph_type = subgraph_type,
                init_vertex = init_vertex
            )
            if not cursor.goto_next_sibling():
                break
        cursor.goto_parent()

    return n_factors, n_vertices_num, n_vertices_type, subgraph_type, init_vertex

class NodePerturabation:
    def __init__(self, code, tree, n_vertices_num, n_vertices_type, eval_input):
        self.code = code
        self.tree = tree
        self.n_vertices_num = n_vertices_num
        self.n_vertices_type = n_vertices_type
        self.eval_input = eval_input
        self.op = ['+', '-', '*', '/']
        self.compare = ['>', '<', '>=', '<=', '==', '!=']
        self.num = len(n_vertices_num) - 1

    def mutate(self, node):
        if node.child_count:
            for child in reversed(node.children):
                self.code = self.mutate(child)

        mutate_code = self.code

        self.tree = parser.parse(mutate_code.encode(), self.tree)
        x = self.tree.root_node.descendant_for_byte_range(node.start_byte, node.start_byte + 1)
        while x and x.type != node.type:
            x = x.parent
        if x and x.type == node.type:
            node = x

        if node.type == 'assignment_expression' or node.type == 'binary_expression':
            for child in node.children:
                if child.type in self.op:
                    assert self.n_vertices_type[self.num] == 'op'
                    assert self.eval_input[self.num] < self.n_vertices_num[self.num]
                    mutate_text = self.op[self.eval_input[self.num]]
                    self.num -= 1
                    start_byte, end_byte = child.start_byte, child.end_byte
                    mutate_code = mutate_code[:start_byte] + mutate_text + mutate_code[end_byte:]

                    ret_start_byte, ret_end_byte = start_byte, start_byte + len(mutate_text)
                    self.tree.edit(
                        start_byte = start_byte,
                        old_end_byte = end_byte,
                        new_end_byte = start_byte + len(mutate_text),
                        start_point = child.start_point,
                        old_end_point = child.end_point,
                        new_end_point = (
                            child.start_point[0],
                            child.start_point[1] + len(mutate_text)
                        )
                    )
                    self.tree = parser.parse(mutate_code.encode(), self.tree)
                    child = self.tree.root_node.descendant_for_byte_range(ret_start_byte, ret_end_byte)

        elif node.type in self.compare:
            assert self.n_vertices_type[self.num] == 'compare'
            assert self.eval_input[self.num] < self.n_vertices_num[self.num]
            mutate_text = self.compare[self.eval_input[self.num]]
            self.num -= 1
            start_byte, end_byte = node.start_byte, node.end_byte
            mutate_code = mutate_code[:start_byte] + mutate_text + mutate_code[end_byte:]

            ret_start_byte, ret_end_byte = start_byte, start_byte + len(mutate_text)
            self.tree.edit(
                start_byte = start_byte,
                old_end_byte = end_byte,
                new_end_byte = start_byte + len(mutate_text),
                start_point = node.start_point,
                old_end_point = node.end_point,
                new_end_point = (
                    node.start_point[0],
                    node.start_point[1] + len(mutate_text)
                )
            )
            self.tree = parser.parse(mutate_code.encode(), self.tree)
            node = self.tree.root_node.descendant_for_byte_range(ret_start_byte, ret_end_byte)

        elif node.type == 'if_statement':
            assert self.n_vertices_type[self.num] == 'if'
            assert self.eval_input[self.num] < self.n_vertices_num[self.num]
            choice = self.eval_input[self.num]
            self.num -= 1
            if choice == 0:
                pass
            
            elif choice == 1:
                if_text = node.child_by_field_name('consequence')
                else_branch = node.child_by_field_name('alternative')
                mutate_code = mutate_code[:if_text.end_byte] + mutate_code[else_branch.end_byte:]
                
                ret_start_byte, ret_end_byte = node.start_byte, node.end_byte - (else_branch.end_byte - if_text.end_byte)
                self.tree.edit(
                    start_byte = node.start_byte,
                    old_end_byte = node.end_byte,
                    new_end_byte = node.end_byte - (else_branch.end_byte - if_text.end_byte),
                    start_point = node.start_point,
                    old_end_point = node.end_point,
                    new_end_point = (
                        if_text.end_point[0],
                        node.end_point[1]
                    )
                )
                self.tree = parser.parse(mutate_code.encode(), self.tree)
                node = self.tree.root_node.descendant_for_byte_range(ret_start_byte, ret_end_byte)

            else:
                if_text = node.child_by_field_name('consequence')
                else_branch = node.child_by_field_name('alternative')
                if else_branch.children[1].type == 'compound_statement':
                    else_text = else_branch.children[1]
                else:
                    else_text = else_branch.children[1].child_by_field_name('consequence')
                mutate_code = mutate_code[:if_text.start_byte] + mutate_code[else_text.start_byte:else_text.end_byte] + mutate_code[else_text.end_byte:]
                
                ret_start_byte, ret_end_byte = node.start_byte, node.end_byte - (else_text.start_byte - if_text.start_byte)
                self.tree.edit(
                    start_byte = node.start_byte,
                    old_end_byte = node.end_byte,
                    new_end_byte = node.end_byte - (else_text.start_byte - if_text.start_byte),
                    start_point = node.start_point,
                    old_end_point = node.end_point,
                    new_end_point = (
                        node.start_point[0] + (if_text.start_point[0] - node.start_point[0]) + (else_text.end_point[0] - else_text.start_point[0]),
                        node.end_point[1]
                    )
                )
                self.tree = parser.parse(mutate_code.encode(), self.tree)
                node = self.tree.root_node.descendant_for_byte_range(ret_start_byte, ret_end_byte)

        self.code = mutate_code
        return self.code

def Vertice_Info(code):
    tree = parser.parse(code.encode())
    root_node = tree.root_node
    cursor = root_node.walk()
    n_factors, n_vertices_num, n_vertices_type, subgraph_type, init_vertex = NodeCounter(
        cursor = cursor,
        code = code,
        n_factors = 0,
        n_vertices_num = [],
        n_vertices_type = [],
        subgraph_type = [],
        init_vertex = []
    )
    return code, n_factors, np.array(n_vertices_num), np.array(n_vertices_type), np.array(subgraph_type), np.array(init_vertex)