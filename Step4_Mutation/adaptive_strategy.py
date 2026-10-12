"""
自适应变异策略：在结构变异和值变异之间动态分配子代数。

ε-greedy 自适应策略：
  - 每种操作类型维护 (尝试次数, 产生新覆盖次数) 统计
  - 每代根据历史成功率分配子代数
  - ε 概率随机探索，1-ε 按成功率比例分配 exploit 配额

所有子代先执行语义交叉，再按本策略选择一种变异类型。
"""

import random
from typing import Dict, List, Optional, Set
from Utils.file_utils import write_log

LOG_PATH = "log.txt"

# 操作类型
OP_MUTATION_STRUCTURAL = "mutation_structural"
OP_MUTATION_VALUE = "mutation_value"

ALL_OPS = [OP_MUTATION_STRUCTURAL, OP_MUTATION_VALUE]


class AdaptiveStrategy:
    """自适应操作分配策略。

    每代结束后调用 update() 更新统计；
    下一代开始前调用 allocate() 获取分配方案。
    """

    def __init__(self, epsilon: float = 0.2):
        self.epsilon = epsilon
        self.stats: Dict[str, Dict[str, int]] = {
            op: {"attempts": 0, "new_coverage": 0}
            for op in ALL_OPS
        }
        # 记录每代中每个子代使用的方法（索引 → 方法），用于归因
        self._gen_methods: List[str] = []
        # 历史 campaign 已覆盖的分支。第一代由 main.py 用初始种群建立基线。
        self._covered_branches: Set[str] = set()

    def allocate(self, total_offspring: int) -> Dict[str, int]:
        """
        分配本代各操作的子代数。

        返回: {OP_MUTATION_STRUCTURAL: n, OP_MUTATION_VALUE: n}
        """
        # 计算各操作的历史成功率
        scores = {
            op: self.stats[op]["new_coverage"] / max(self.stats[op]["attempts"], 1)
            for op in ALL_OPS
        }

        # ε-贪心：预留比例给随机探索
        explore = max(int(total_offspring * self.epsilon), 0)
        exploit = total_offspring - explore

        # 尚无反馈时均匀冷启动；之后按历史成功率分配 exploit 配额。
        total_score = sum(scores.values())
        alloc = {op: 0 for op in ALL_OPS}
        if total_score == 0:
            for i in range(exploit):
                alloc[ALL_OPS[i % len(ALL_OPS)]] += 1
        else:
            for op in ALL_OPS:
                alloc[op] = int(scores[op] / total_score * exploit)

        # 分配剩余的 explore 配额
        remaining = exploit - sum(alloc.values())
        for i in range(remaining):
            weights = [max(scores[op], 0.01) for op in ALL_OPS]
            op = random.choices(ALL_OPS, weights=weights)[0]
            alloc[op] += 1

        # 随机分配 explore 部分
        for _ in range(explore):
            op = random.choice(ALL_OPS)
            alloc[op] += 1

        # 验证总数
        assert sum(alloc.values()) == total_offspring, (
            f"Allocation sum {sum(alloc.values())} != {total_offspring}"
        )

        return alloc

    def set_methods_for_gen(self, methods: List[str]) -> None:
        """记录本代每个子代使用的方法（索引对齐 offspring 列表）。"""
        self._gen_methods = list(methods)

    def record_attempts(self, methods: Optional[List[str]] = None) -> None:
        """记录操作尝试；reboot 的重新生成也必须计入。"""
        for method in self._gen_methods if methods is None else methods:
            if method in self.stats:
                self.stats[method]["attempts"] += 1

    @property
    def covered_branches(self) -> Set[str]:
        return set(self._covered_branches)

    def establish_baseline(self, branches: Set[str]) -> None:
        """把初始种群或既有 campaign 覆盖加入归因基线。"""
        self._covered_branches.update(branches)

    def update(self, offspring_branches: List[Set[str]]) -> Dict[str, int]:
        """
        根据覆盖率结果更新各操作的 new_coverage 计数。

        Parameters
        ----------
        offspring_branches : List[Set[str]]
            每个子代覆盖的分支集合（与 _gen_methods 索引对齐）。

        Returns
        -------
        dict: 各操作本代的新覆盖统计
        """
        if len(offspring_branches) != len(self._gen_methods):
            raise ValueError("offspring coverage and method attribution must be index-aligned")

        baseline = set(self._covered_branches)
        gen_stats = {op: 0 for op in ALL_OPS}
        for i, method in enumerate(self._gen_methods):
            if method in self.stats and offspring_branches[i] - baseline:
                # 成功率以成功的尝试次数计数，而不是新增分支数量。
                self.stats[method]["new_coverage"] += 1
                gen_stats[method] += 1

        # Judge every attempt against the same start-of-generation baseline.
        for branches in offspring_branches:
            self._covered_branches.update(branches)

        return gen_stats

    def log_stats(self) -> None:
        """输出当前统计到 log。"""
        lines = ["Adaptive Strategy Stats:"]
        for op in ALL_OPS:
            s = self.stats[op]
            rate = s["new_coverage"] / max(s["attempts"], 1)
            lines.append(
                f"  {op}: attempts={s['attempts']}, "
                f"successful_attempts={s['new_coverage']}, "
                f"rate={rate:.3f}"
            )
        write_log(LOG_PATH, "\n".join(lines) + "\n")

    def log_allocation(self, alloc: Dict[str, int]) -> None:
        """输出本代分配方案到 log。"""
        parts = [f"{op}={alloc[op]}" for op in ALL_OPS]
        write_log(LOG_PATH, f"Adaptive allocation: {', '.join(parts)}\n")


# 全局单例（跨代持久化）
_strategy: Optional[AdaptiveStrategy] = None


def get_strategy() -> AdaptiveStrategy:
    """获取或创建全局策略实例。"""
    global _strategy
    if _strategy is None:
        _strategy = AdaptiveStrategy()
    return _strategy
