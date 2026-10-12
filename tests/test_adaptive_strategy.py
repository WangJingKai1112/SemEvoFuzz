from Step4_Mutation.adaptive_strategy import (
    ALL_OPS,
    AdaptiveStrategy,
    OP_MUTATION_STRUCTURAL,
    OP_MUTATION_VALUE,
)


def test_allocation_preserves_requested_population_size():
    strategy = AdaptiveStrategy(epsilon=0.2)
    allocation = strategy.allocate(30)

    assert set(allocation) == set(ALL_OPS)
    assert sum(allocation.values()) == 30


def test_coverage_attribution_updates_operator_statistics():
    strategy = AdaptiveStrategy(epsilon=0.0)
    strategy.establish_baseline({"b0"})
    strategy.set_methods_for_gen([
        OP_MUTATION_STRUCTURAL,
        OP_MUTATION_VALUE,
    ])
    strategy.record_attempts()

    generation = strategy.update([{"b0", "b1"}, {"b0"}])

    assert generation[OP_MUTATION_STRUCTURAL] == 1
    assert generation[OP_MUTATION_VALUE] == 0
    assert strategy.covered_branches == {"b0", "b1"}

