import torch
import random
from tree_sitter import Language, Parser
from Step3_Crossover.ast_information import has_uninitialized_reads
from Step4_Mutation.graph_information import collect_mutation_targets, vertex_info
from Step4_Mutation.graph_mutation import graphInfo, graphMutaton
from Step4_Mutation.graph_neighbor import get_neighbors
from Utils.file_utils import write_log

parser = Parser()
parser.set_language(Language("Libs/tree_sitter/parser/my-languages.so", "c"))
log_path = "log.txt"


def process(code: str, mutation_steps: int, mutation_type: str = None,
            target: str = None) -> str:
    """
    对单个程序执行图谱变异。

    Parameters
    ----------
    mutation_type : str or None
        None  → 全部变异（向后兼容）
        "structural" → 控制流、循环展开和调用序列变异
        "value" → 运算符、常量、索引和局部类型变异
    """
    targets = collect_mutation_targets(code, mutation_type)
    if not targets:
        return code
    mutation_kind = random.choice(list(dict.fromkeys(
        target["kind"] for target in targets
    )))
    factors, vertex_num, vertex_type, subgraph_type, initial_vertex = \
        vertex_info(code, mutation_type=mutation_type,
                    mutation_kind=mutation_kind)
    if factors == 0:
        return code
    objective = graphInfo(factors, vertex_num, vertex_type, subgraph_type, initial_vertex)
    adjacency_matrix = objective.adjacency_matrix
    L_known = objective.suggest_init
    for i in range(5):
        suggestion = L_known[-1:].clone()
        for _ in range(mutation_steps):
            neighbors = get_neighbors(L_known, adjacency_matrix, True)
            if neighbors.size(0) > 0:
                suggestion = neighbors[torch.randint(0, neighbors.size(0), (1,)).item()].unsqueeze(0)
                L_known = torch.cat([L_known, suggestion], dim=0)
            else:
                suggestion = L_known[torch.randint(0, L_known.size(0), (1,)).item()].unsqueeze(0)

        ret = graphMutaton(
            code,
            parser.parse(code.encode()),
            vertex_num,
            vertex_type,
            suggestion[0],
            mutation_type=mutation_type,
            mutation_kind=mutation_kind,
        )
        ret.mutate(parser.parse(code.encode()).root_node)
        accepted = (
            ret.code != ""
            and not has_uninitialized_reads(ret.code)
        )
        if accepted:
            return ret.code
        if i == 4:
            return code


def mutation(population: list, mutation_steps: int, reboot_idx: list = None,
             mutation_types: list = None) -> list:
    """
    对种群执行变异。

    Parameters
    ----------
    mutation_types : list[str] or None
        每个程序对应的变异类型列表，长度必须与 population 一致。
        None → 全部使用默认（全部变异）。
    """
    if reboot_idx is None:
        reboot_idx = []

    results = []
    if not reboot_idx:
        for i, prog in enumerate(population):
            mtype = mutation_types[i] if mutation_types else None
            results.append(process(prog, mutation_steps, mutation_type=mtype))
        write_log(log_path, f"Step4 finished. Performed mutation on {len(results)} programs (normal).\n")
    else:
        for i in range(len(population)):
            if i in reboot_idx:
                mtype = mutation_types[i] if mutation_types else None
                results.append(process(population[i], mutation_steps, mutation_type=mtype))
            else:
                results.append(population[i])
        write_log(log_path, f"Step4 finished. Performed mutation on {len(results)} programs (reboot).\n")
    return results
