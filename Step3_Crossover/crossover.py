import random

from tree_sitter import Language, Parser
from Step3_Crossover.ast_information import (
    extract_func_and_decl,
    get_swap_list,
    has_uninitialized_reads,
)
from Step3_Crossover.ast_operation import (
    cross_block,
    cross_nodes,
    get_statement_blocks,
    get_var_and_decl_info,
    rename_block,
    rename_nodes,
    select_nodes,
    select_statement_blocks,
)
from Utils.file_utils import write_log

parser = Parser()
parser.set_language(Language("Libs/tree_sitter/parser/my-languages.so", "c"))
log_path = "log.txt"


def _effective_children(candidates: list, parent_1: str, parent_2: str) -> list:
    return [
        child for child in candidates
        if child != parent_1 and child != parent_2
        and not has_uninitialized_reads(child)
    ]


def _cross_statement_blocks(parent_1: str, parent_2: str,
                            func_def_1: list, func_def_2: list,
                            global_decl_1: list,
                            global_decl_2: list) -> list:
    blocks_1 = get_statement_blocks(func_def_1)
    blocks_2 = get_statement_blocks(func_def_2)
    for _ in range(4):
        select_1, select_2 = select_statement_blocks(list(blocks_1), blocks_2)
        if select_1 is None or select_2 is None:
            break
        func_index_1, block_1 = select_1
        func_index_2, block_2 = select_2
        var_all_1, decl_all_1 = get_var_and_decl_info(
            func_def_1[func_index_1], global_decl_1, block_1[0], parent_1
        )
        var_all_2, decl_all_2 = get_var_and_decl_info(
            func_def_2[func_index_2], global_decl_2, block_2[0], parent_2
        )
        decl_1, segment_1 = rename_block(
            var_all_2, decl_all_1, block_1, parent_1
        )
        decl_2, segment_2 = rename_block(
            var_all_1, decl_all_2, block_2, parent_2
        )
        candidates = [
            cross_block(
                parent_1, block_1, func_def_1[func_index_1], segment_2, decl_2
            ),
            cross_block(
                parent_2, block_2, func_def_2[func_index_2], segment_1, decl_1
            ),
        ]
        effective = _effective_children(candidates, parent_1, parent_2)
        if effective:
            return effective
    return []


def _cross_ast_nodes(parent_1: str, parent_2: str,
                     func_def_1: list, func_def_2: list,
                     global_decl_1: list, global_decl_2: list) -> list:
    swap_list_1, swap_list_2 = get_swap_list(func_def_1), get_swap_list(func_def_2)
    for _ in range(8):
        select_1, select_2 = select_nodes(list(swap_list_1), swap_list_2)
        if select_1 is None or select_2 is None:
            break
        var_all_1, decl_all_1 = get_var_and_decl_info(
            func_def_1[select_1[0]], global_decl_1, select_1[1], parent_1
        )
        var_all_2, decl_all_2 = get_var_and_decl_info(
            func_def_2[select_2[0]], global_decl_2, select_2[1], parent_2
        )
        decl_1, segment_1 = rename_nodes(
            var_all_2, decl_all_1, select_1[1], parent_1
        )
        decl_2, segment_2 = rename_nodes(
            var_all_1, decl_all_2, select_2[1], parent_2
        )
        candidates = [
            cross_nodes(
                parent_1, select_1[1], func_def_1[select_1[0]], segment_2, decl_2
            ),
            cross_nodes(
                parent_2, select_2[1], func_def_2[select_2[0]], segment_1, decl_1
            ),
        ]
        effective = _effective_children(candidates, parent_1, parent_2)
        if effective:
            return effective
    return []

def process(population: list, pair: list) -> list:
    # 获取亲代
    parent_1, parent_2 = population[pair[0]], population[pair[1]]
    # 解析为语法树
    tree_1, tree_2 = parser.parse(parent_1.encode()), parser.parse(parent_2.encode())
    root_1, root_2 = tree_1.root_node, tree_2.root_node
    # 提取函数定义和全局变量
    func_def_1, global_decl_1 = extract_func_and_decl(root_1)
    func_def_2, global_decl_2 = extract_func_and_decl(root_2)
    # Keep the established AST crossover as the primary path.  Block
    # crossover contributes additional candidates instead of replacing it.
    ast_children = _cross_ast_nodes(
        parent_1, parent_2,
        func_def_1, func_def_2,
        global_decl_1, global_decl_2,
    )
    block_children = _cross_statement_blocks(
        parent_1, parent_2,
        func_def_1, func_def_2,
        global_decl_1, global_decl_2,
    )
    ast_children = list(dict.fromkeys(ast_children))
    block_children = list(dict.fromkeys(block_children))

    # A pair contributes at most two children, so adding block crossover does
    # not reduce the number of distinct parent pairings in one generation.
    if ast_children and block_children:
        ast_child = random.choice(ast_children)
        distinct_blocks = [child for child in block_children
                           if child != ast_child]
        if distinct_blocks:
            return [ast_child, random.choice(distinct_blocks)]

    available = list(dict.fromkeys(ast_children + block_children))
    random.shuffle(available)
    return available[:2]


def crossover(population: list, pairs: list, offspring: list = None,
              reboot_idx: list = None) -> list:
    if offspring is None:
        offspring = []
    if reboot_idx is None:
        reboot_idx = []
    results = []
    for pair in pairs:
        results.extend(process(population, pair))
    if reboot_idx == []:
        write_log(log_path, f"Step3 finished. Performed crossover on {len(results)} programs (normal).\n")
        return results
    else:
        assert len(reboot_idx) <= len(offspring)
        for i in range(len(reboot_idx)):
            offspring[reboot_idx[i]] = results[i]
        write_log(log_path, f"Step3 finished. Performed crossover on {len(reboot_idx)} programs (reboot).\n")
        return offspring
