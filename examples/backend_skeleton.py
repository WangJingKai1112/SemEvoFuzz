"""Minimal shape of a SemEvoFuzz execution backend."""

from pathlib import Path

from semevofuzz_core import Evaluation


class ExampleBackend:
    name = "example"

    def initialize(self, population_size, client, model, log, deadline):
        raise NotImplementedError("connect a program initializer")

    def compile_one(self, code, index):
        raise NotImplementedError("write source, invoke compiler, return status and log")

    def compile(self, programs, indices):
        return [self.compile_one(code, index)[0]
                for code, index in zip(programs, indices)]

    def evaluate(self, offspring, population, generation, start_index,
                 workers, simlen, timeout, max_generation):
        # Execute offspring + population and return index-aligned coverage data.
        raise NotImplementedError("run target and return an Evaluation")

    def write_selected(self, population, result_dir):
        output = Path(result_dir) / "selected"
        output.mkdir(parents=True, exist_ok=True)
        for index, code in enumerate(population):
            (output / f"test_{index}.c").write_text(code, encoding="utf-8")


def empty_evaluation(result_dir):
    """Build an empty result for adapter smoke tests."""
    return Evaluation(
        records=[],
        metrics={},
        result_dir=Path(result_dir),
        branch_sets=[],
    )

