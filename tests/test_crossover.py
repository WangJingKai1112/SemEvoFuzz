import random

from Step3_Crossover.crossover import parser, process


PARENTS = [
    """
    int main(void) {
        int x = 1;
        int y = x + 2;
        if (y < 8) {
            y += x;
        }
        return y;
    }
    """,
    """
    int main(void) {
        int a = 4;
        int b = a * 3;
        if (b > 5) {
            b -= a;
        }
        return b;
    }
    """,
]


def test_crossover_produces_parseable_changed_offspring():
    random.seed(7)
    offspring = process(PARENTS, [0, 1])

    assert 1 <= len(offspring) <= 2
    assert len(set(offspring)) == len(offspring)
    for child in offspring:
        assert child not in PARENTS
        assert not parser.parse(child.encode()).root_node.has_error

