"""
Hill Numbers 行为多样性度量：
  - 将每个 RTL branch bin 视为"物种"
  - 物种丰度 c(b) = 覆盖分支 b 的不同测试程序数（unique traces）
  - B(0) = 分支总数（richness）
  - B(1) = 典型覆盖的有效分支数（Shannon exponential）
  - B(2) = 常见覆盖的有效分支数（inverse Simpson）

B(1)/B(2) 是测试集合级（campaign-level）指标，不能直接作为单程序 fitness。
"""

from typing import List, Set
import numpy as np


def hill_number(branch_trace_counts: np.ndarray, q: int) -> float:
    """
    计算 Hill Number of order q。

    Parameters
    ----------
    branch_trace_counts : np.ndarray, shape (S,)
        每个 branch bin 被多少不同测试（unique traces）覆盖的计数。
    q : int
        Hill number 的阶数。
        q=0: richness（= 被覆盖的物种总数）
        q=1: Shannon exponential（典型物种的有效数量）
        q=2: inverse Simpson（常见物种的有效数量）

    Returns
    -------
    float
        Hill number D(q)
    """
    if q == 0:
        return float(len(branch_trace_counts))

    total = branch_trace_counts.sum()
    if total == 0:
        return 0.0

    # 相对丰度
    p = branch_trace_counts.astype(np.float64) / float(total)

    if q == 1:
        # Shannon exponential: exp(-sum(p_i * log(p_i)))
        p_pos = p[p > 0]
        if len(p_pos) == 0:
            return 0.0
        return float(np.exp(-np.sum(p_pos * np.log(p_pos))))
    else:
        # 通用公式: (sum(p_i^q))^(1/(1-q))
        return float(np.sum(p ** q) ** (1.0 / (1.0 - q)))


def compute_behavioral_diversity(
    coverage_matrix: np.ndarray,
) -> dict:
    """
    从二值覆盖矩阵计算行为多样性指标。

    Parameters
    ----------
    coverage_matrix : np.ndarray, shape (n_tests, n_branches)
        二值矩阵：coverage_matrix[i, j] = 1 表示测试 i 覆盖了分支 j。

    Returns
    -------
    dict with keys:
        B0 : float   — 被覆盖的分支总数
        B1 : float   — 典型覆盖的有效分支数
        B2 : float   — 常见覆盖的有效分支数
        n_tests : int
        n_branches_covered : int
        n_branches_total : int
    """
    n_tests, n_branches = coverage_matrix.shape

    branch_coverage_counts = coverage_matrix.sum(axis=0).astype(np.int32)

    covered = branch_coverage_counts[branch_coverage_counts > 0]
    n_branches_covered = len(covered)

    if n_branches_covered == 0:
        return {
            "B0": 0.0,
            "B1": 0.0,
            "B2": 0.0,
            "n_tests": n_tests,
            "n_branches_covered": 0,
            "n_branches_total": n_branches,
        }

    return {
        "B0": hill_number(covered, 0),
        "B1": hill_number(covered, 1),
        "B2": hill_number(covered, 2),
        "n_tests": n_tests,
        "n_branches_covered": n_branches_covered,
        "n_branches_total": n_branches,
    }


def build_coverage_matrix_from_per_test(
    per_test_branches,
    all_branch_ids,
) -> np.ndarray:
    """
    从 per-test 覆盖模块集合构建二值覆盖矩阵。

    Parameters
    ----------
    per_test_branches : List[Set[str]]
        每个测试覆盖的 branch-bin ID 集合。
    all_branch_ids : List[str]
        所有 branch-bin ID（用于列对齐）。

    Returns
    -------
    np.ndarray, shape (n_tests, n_branches), dtype=bool
    """
    branch_to_idx = {name: i for i, name in enumerate(all_branch_ids)}
    n_tests = len(per_test_branches)
    n_branches = len(all_branch_ids)

    matrix = np.zeros((n_tests, n_branches), dtype=bool)
    for i, covered in enumerate(per_test_branches):
        for branch_id in covered:
            if branch_id in branch_to_idx:
                matrix[i, branch_to_idx[branch_id]] = True

    return matrix
