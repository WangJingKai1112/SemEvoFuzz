import random

import torch

from Step4_Mutation.mutation import parser, process


PROGRAM = """
int main(void) {
    int x = 1;
    int y = 2;
    x = x + y;
    if (x < 8) {
        x = x ^ 3;
    }
    return x;
}
"""


def test_value_mutation_produces_parseable_edit():
    random.seed(7)
    torch.manual_seed(7)
    mutated = process(PROGRAM, mutation_steps=2, mutation_type="value")

    assert mutated != PROGRAM
    assert not parser.parse(mutated.encode()).root_node.has_error
