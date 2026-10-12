# Backend interface

`run_evolution(backend, args, client, model, log)` delegates target-specific
compilation and evaluation to `backend`. Implement the following members:

The compilation methods provide Step 5; `evaluate` provides the simulation and
coverage collection in Step 7. These capabilities are implemented in your
backend rather than separate directories in this repository.

```python
class Backend:
    name: str

    def initialize(self, population_size, client, model, log, deadline): ...
    def compile_one(self, code, index): ...
    def compile(self, programs, indices): ...
    def evaluate(
        self, offspring, population, generation, start_index,
        workers, simlen, timeout, max_generation
    ): ...
    def write_selected(self, population, result_dir): ...
```

## Compilation adapter

`initialize` returns `population_size` C programs. `compile_one` receives the
source text and test index, builds one test, and returns `(status, build_log)`.
Status `1` denotes success; `build_log` is passed to the repair loop after a
failure. `compile` applies the same operation to an index-aligned program list
and returns one status per program.

The adapter owns source placement, compiler invocation, generated binaries, and
temporary build directories.

## Execution and coverage adapter

`evaluate` executes `offspring + population`, in that order, and returns an
`Evaluation` object:

- `records`: one dictionary per evaluated program, in the same order. Each
  dictionary must contain numeric `SCORE`; additional fields are preserved in
  `selected_coverage.csv`.
- `metrics`: campaign-level values for `SCORE`, `LINE`, `COND`, `TOGGLE`, `FSM`,
  and `BRANCH`. Use `0.0` for an unavailable metric.
- `result_dir`: checkpoint directory used for selection output and the campaign
  log.
- `branch_sets`: one set of stable branch identifiers per evaluated program,
  in the same order as `records`.

Coverage values use percentages on a 0–100 scale. With all five coverage metrics
available, `SCORE` is their arithmetic mean. Per-test scores drive population
selection; campaign metrics drive stagnation detection. Aggregate coverage by
combining covered items across tests, rather than averaging per-test percentages.

The adapter therefore performs four operations:

1. materialize or locate the executable for every program;
2. run each program on the target;
3. collect per-program coverage and aggregate campaign metrics; and
4. translate those results into `records`, `metrics`, and `branch_sets`.

The following shape is sufficient:

```python
def evaluate(self, offspring, population, generation, start_index,
             workers, simlen, timeout, max_generation):
    programs = offspring + population
    raw_results = [self.run_test(code, start_index + i)
                   for i, code in enumerate(programs)]
    records = [self.coverage_record(result) for result in raw_results]
    branch_sets = [self.branch_ids(result) for result in raw_results]
    metrics = self.aggregate_metrics(raw_results)
    return Evaluation(records, metrics, self.checkpoint_dir(generation),
                      branch_sets)
```

`write_selected` persists the selected source programs for the next generation.
`examples/backend_skeleton.py` provides the complete method layout.

## Driver arguments

The `args` object passed to `run_evolution` provides `seed`, `population_size`,
`max_generation`, `mutation_steps`, `max_debug_loop`, `workers`, `simlen`,
`timeout`, `duration_seconds`, `start_elite_ratio`, `end_elite_ratio`,
`strategy_factory`, and optional `ablation`.

