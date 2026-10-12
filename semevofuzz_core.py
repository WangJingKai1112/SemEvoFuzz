from __future__ import annotations
import csv, json, random, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from Step1_Initialization.prompt import gap_guided_prompt, llmFormat, llm_prompt
from Step2_Mating.mating import mating
from Step3_Crossover.crossover import process as crossover_process
from Step3_Crossover.ast_information import has_uninitialized_reads
from Step4_Mutation.adaptive_strategy import OP_MUTATION_STRUCTURAL, OP_MUTATION_VALUE
from Step4_Mutation.mutation import process as mutation_process
from Step6_Debugging_and_Rebooting.prompt import extractLogFormat, extract_log_prompt, fixCodeFormat, fixSuggestionsFormat, fix_code_prompt, fix_suggestions_prompt
from Utils.diversity_metrics import build_coverage_matrix_from_per_test, compute_behavioral_diversity

OP_LLM_IMMIGRANT = "llm_immigrant"
OP_CROSSOVER_ONLY = "crossover_only"
OP_PARENT_ONLY = "parent_only"
METRICS = ("SCORE", "LINE", "COND", "TOGGLE", "FSM", "BRANCH")

@dataclass
class Evaluation:
    records: list[dict]
    metrics: dict[str, Any]
    result_dir: Path
    branch_sets: list[set[str]]


def _log(path, text):
    print(text, end="", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f: f.write(text)


def _parse(client, model, fmt, prompt, temperature=0.2, retries=10):
    last = None
    for attempt in range(retries):
        try:
            r = client.beta.chat.completions.parse(model=model, messages=[{"role":"user","content":prompt}], temperature=temperature, response_format=fmt, max_completion_tokens=16384)
            return r.choices[0].message.parsed
        except Exception as e:
            last = e
            if attempt + 1 < retries: time.sleep(10)
    raise last


def _request_code(client, model, prompt, deadline=None, retries=4):
    """Request one program while bounding transient API failures."""
    last_error = None
    for attempt in range(retries):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("experiment deadline reached while requesting C code")
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                response_format=llmFormat,
                max_tokens=4196,
            )
            code = response.choices[0].message.parsed.code
            if not code:
                raise ValueError("LLM returned empty C code")
            return code
        except Exception as error:
            last_error = error
            if attempt + 1 < retries:
                delay = min(2 ** attempt, 8)
                if deadline is not None:
                    delay = min(delay, max(0.0, deadline - time.monotonic()))
                if delay > 0:
                    time.sleep(delay)
    raise RuntimeError(f"LLM code request failed after {retries} attempts: {last_error}") from last_error


def initialize_population(backend, size, client, model, log, deadline=None):
    population = []
    attempts = 0
    max_attempts = max(size * 20, size + 10)
    while len(population) < size:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(f"experiment deadline reached during initialization ({len(population)}/{size} valid)")
        attempts += 1
        if attempts > max_attempts:
            raise RuntimeError(f"unable to initialize {size} target-valid programs after {attempts - 1} attempts")
        try:
            code = _request_code(client, model, llm_prompt(getattr(backend, "name", "c910")), deadline)
        except Exception as error:
            _log(log, f"[initialization] code request failed: {error}\n")
            continue
        if has_uninitialized_reads(code):
            _log(log, "[initialization] rejected candidate with uninitialized reads\n")
            continue
        status, _ = backend.compile_one(code, len(population))
        if status == 1:
            population.append(code)
            _log(log, f"Generated test_{len(population) - 1}.c by LLM.\n")
        else:
            _log(log, f"[initialization] target compiler rejected candidate (attempt {attempts})\n")
    return population


def _gap_immigrant(backend, client, model, gaps, index, deadline=None):
    prompt = gap_guided_prompt(gaps, getattr(backend, "name", "c910"))
    for _ in range(20):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("experiment deadline reached while creating an immigrant")
        code = _request_code(client, model, prompt, deadline)
        if has_uninitialized_reads(code):
            continue
        status, _ = backend.compile_one(code, index)
        if status == 1:
            return code
    raise RuntimeError("unable to create a target-valid immigrant after 20 attempts")


def _children(population, scores, count, mutation_steps, allocation, target=None,
              disable_crossover=False, disable_mutation=False):
    mutation_methods = [OP_MUTATION_STRUCTURAL] * allocation[OP_MUTATION_STRUCTURAL] + [OP_MUTATION_VALUE] * allocation[OP_MUTATION_VALUE]
    methods = [] if disable_mutation else mutation_methods
    random.shuffle(methods)
    out = []
    attempts = 0
    while len(out) < count and attempts < max(40, count * 20):
        pair = mating(len(population), 1, True, scores)[0]
        if disable_crossover:
            # Keep mating and the mutation operator intact, but use the
            # selected parents as mutation inputs instead of recombining them.
            candidates = [population[pair[0]], population[pair[1]]]
        else:
            candidates = crossover_process(population, pair)
            if disable_mutation and not candidates:
                # Crossover can legitimately find no compatible AST nodes.
                # The no-mutation control still needs a fixed-size batch, so
                # preserve the selected parent as an unchanged child.
                candidates = [population[pair[0]], population[pair[1]]]
        for child in candidates:
            if len(out) >= count: break
            if disable_mutation:
                out.append(child)
                methods.append(OP_PARENT_ONLY if disable_crossover else OP_CROSSOVER_ONLY)
            else:
                kind = "structural" if methods[len(out)] == OP_MUTATION_STRUCTURAL else "value"
                out.append(mutation_process(child, mutation_steps, kind, target=target))
        attempts += 1
    if len(out) != count: raise RuntimeError("unable to generate enough ablation offspring")
    return out, methods


def _gaps(history, generation, last_generation, last_gaps, last_metrics):
    if len(history) < 4:
        return []
    if generation - last_generation < 3:
        return []
    current = history[-1]
    blocked = {
        dimension for dimension in last_gaps
        if dimension in last_metrics
        and current[dimension] - last_metrics[dimension] <= 0.05
    }

    def stagnation_level(dimension):
        recent_gain = current[dimension] - history[-4][dimension]
        prior_gains = [
            history[end][dimension] - history[end - 3][dimension]
            for end in range(3, len(history) - 3)
        ]
        prior_gain = sum(prior_gains) / len(prior_gains) if prior_gains else 0.0
        relative_recent_gain = recent_gain / max(history[-4][dimension], 1.0)
        if prior_gain > 0.0:
            return recent_gain / prior_gain, relative_recent_gain
        return relative_recent_gain, relative_recent_gain

    candidates = [
        dimension for dimension in ("FSM", "TOGGLE")
        if dimension not in blocked
        and current[dimension] - history[-4][dimension] <= 0.10
    ]
    return sorted(candidates, key=stagnation_level)[:2]


def _immigrant_count(gaps, population_size, ablation):
    if not gaps or ablation == "no_llm_immigrant":
        return 0
    return max(1, population_size // 10)


def _select(programs, records, size, progress, start_ratio, end_ratio, folder):
    import numpy as np
    scores = [float(r.get("SCORE", 0.0)) / 100.0 for r in records]
    candidate_count = min(len(programs), len(scores))
    if candidate_count == 0: raise RuntimeError("selection received no scored programs")
    count = min(size, candidate_count)
    ratio = start_ratio + (end_ratio - start_ratio) * progress
    elite_n = int(count * ratio)
    order = sorted(range(candidate_count), key=lambda i: (round(scores[i], 3), scores[i]), reverse=True)
    elite = order[:elite_n]
    rest = [i for i in range(candidate_count) if i not in elite]
    n = count - elite_n
    roulette = []
    if n and rest:
        weights = [scores[i] for i in rest]; total = sum(weights)
        p = [x / total for x in weights] if total else [1.0 / len(rest)] * len(rest)
        try: roulette = list(np.random.choice(rest, size=n, replace=False, p=p))
        except ValueError: roulette = list(np.random.choice(rest, size=n, replace=True, p=p))
    selected = elite + roulette
    while len(selected) < size: selected.append(random.randrange(count))
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "selected_coverage.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0])); w.writeheader(); w.writerows(records[i] for i in selected[:count])
    return [programs[i] for i in selected[:size]], [scores[i] for i in selected[:size]]


def _debug(backend, offspring, methods, population, scores, mutation_steps, max_debug, strategy, gaps, client, model, indices, log, deadline=None, ablation="full"):
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("experiment deadline reached during target compilation/debugging")
        statuses = backend.compile(offspring, indices)
        failed = [i for i, s in enumerate(statuses) if s != 1]
        if not failed: return offspring
        _log(log, f"Debugging failed offspring indices: {failed}\n")
        reboot = []
        for i in failed:
            code = offspring[i]; repaired = False
            for loop in range(max_debug):
                status, build_log = backend.compile_one(code, indices[i])
                if status == 1: repaired = True; break
                _log(log, f"Debugging test_{indices[i]}.c loop: {loop}.\n")
                try:
                    err = _parse(client, model, extractLogFormat, extract_log_prompt(build_log, f"test_{indices[i]}.c"))
                    sug = _parse(client, model, fixSuggestionsFormat, fix_suggestions_prompt(code, err.log))
                    if not sug.suggestions: continue
                    fixed = _parse(client, model, fixCodeFormat, fix_code_prompt(code, sug.suggestions[0])).fixed_code
                    if fixed and not has_uninitialized_reads(fixed): code = fixed; offspring[i] = fixed
                except Exception as e: _log(log, f"[debug] repair request failed: {e}\n")
            if not repaired:
                _log(log, f"[debug] repair exhausted for test_{indices[i]}; rebooting\n")
                if methods[i] == OP_LLM_IMMIGRANT: offspring[i] = _gap_immigrant(backend, client, model, gaps, indices[i], deadline)
                else:
                    child, _ = _children(
                        population, scores, 1, mutation_steps,
                        {OP_MUTATION_STRUCTURAL: int(methods[i] == OP_MUTATION_STRUCTURAL),
                         OP_MUTATION_VALUE: int(methods[i] == OP_MUTATION_VALUE)},
                        target=getattr(backend, "name", None),
                        disable_crossover=ablation == "no_crossover",
                        disable_mutation=ablation == "no_mutation",
                    )
                    offspring[i] = child[0]
                reboot.append(methods[i])
        if reboot: strategy.record_attempts(reboot)


def run_evolution(backend, args, client, model, log):
    random.seed(args.seed)
    start = time.monotonic(); deadline = None if args.duration_seconds is None else start + args.duration_seconds
    ablation = getattr(args, "ablation", "full")
    if ablation not in {"full", "no_crossover", "no_mutation", "no_llm_immigrant"}:
        raise ValueError(f"unsupported ablation: {ablation}")
    _log(log, f"Ablation configuration: {ablation}\n")
    population = backend.initialize(args.population_size, client, model, log, deadline)
    strategy = args.strategy_factory()
    scores = []; history = []; generation = 0; start_idx = 0; evaluated_tests = 0
    last_gen = -3; last_gaps = []; last_metrics = {}; last_result = None
    while (deadline is None or time.monotonic() < deadline) and (not args.max_generation or generation < args.max_generation):
        _log(log, f"---------- Generation {generation + 1} ----------\n")
        gaps = _gaps(history, generation, last_gen, last_gaps, last_metrics)
        immigrant_n = _immigrant_count(gaps, args.population_size, ablation)
        if ablation == "no_mutation":
            allocation = {OP_MUTATION_STRUCTURAL: 0, OP_MUTATION_VALUE: 0}
            _log(log, "Graph-spectral mutation disabled for this campaign.\n")
        else:
            allocation = strategy.allocate(args.population_size - immigrant_n)
            strategy.log_allocation(allocation)
        offspring, methods = _children(
            population, scores, args.population_size - immigrant_n,
            args.mutation_steps, allocation, target=backend.name,
            disable_crossover=ablation == "no_crossover",
            disable_mutation=ablation == "no_mutation",
        )
        if immigrant_n:
            _log(log, f"Gap-guided LLM immigrants: count={immigrant_n}, gaps={','.join(gaps)}\n")
            for _ in range(immigrant_n):
                immigrant_index = start_idx + len(offspring)
                offspring.append(_gap_immigrant(backend, client, model, gaps, immigrant_index, deadline))
                methods.append(OP_LLM_IMMIGRANT)
            paired = list(zip(offspring, methods)); random.shuffle(paired); offspring, methods = map(list, zip(*paired))
            last_gen = generation; last_gaps = list(gaps); last_metrics = dict(history[-1])
        strategy.set_methods_for_gen(methods); strategy.record_attempts()
        child_indices = list(range(start_idx, start_idx + len(offspring)))
        offspring = _debug(backend, offspring, methods, population, scores, args.mutation_steps, args.max_debug_loop, strategy, gaps, client, model, child_indices, log, deadline, ablation)
        evaluation = backend.evaluate(offspring, population, generation, start_idx, args.workers, args.simlen, args.timeout, args.max_generation)
        last_result = evaluation.result_dir
        combined = offspring + population
        if len(evaluation.records) != len(combined): raise RuntimeError("backend returned wrong offspring+parent score count")
        children_branches = evaluation.branch_sets[:len(offspring)]; parent_branches = evaluation.branch_sets[len(offspring):]
        history.append({m: float(evaluation.metrics.get(m, 0.0)) for m in METRICS})
        strategy.establish_baseline(set().union(*parent_branches) if parent_branches else set())
        _log(log, f"Adaptive successes this generation: {strategy.update(children_branches)}\n"); strategy.log_stats()
        all_branches = sorted(set().union(*evaluation.branch_sets)) if evaluation.branch_sets else []
        div = compute_behavioral_diversity(build_coverage_matrix_from_per_test(evaluation.branch_sets, all_branches))
        _log(log, f"Diversity Metrics: B(0)={div['B0']:.1f} B(1)={div['B1']:.2f} B(2)={div['B2']:.2f} (branches: {div['n_branches_covered']}, tests: {div['n_tests']})\n")
        if deadline is None:
            progress = generation / max(args.max_generation - 1, 1)
        else:
            progress = min((time.monotonic() - start) / args.duration_seconds, 1.0)
        population, scores = _select(combined, evaluation.records, args.population_size, progress, args.start_elite_ratio, args.end_elite_ratio, evaluation.result_dir)
        backend.write_selected(population, evaluation.result_dir)
        generation += 1
        start_idx += len(combined)
        # Every evaluation scores offspring and parents (2N in the normal
        # campaign), so report the actual number of tested programs rather
        # than counting offspring only.
        evaluated_tests += len(combined)
        summary_root = getattr(backend, "root", getattr(backend, "results", None))
        if summary_root is not None:
            summary_root = Path(summary_root); summary_root.mkdir(parents=True, exist_ok=True)
            summary_path = summary_root / "summary.csv"
            fields = ["checkpoint", "elapsed_seconds", "tests_completed", *METRICS]
            with summary_path.open("a", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                if summary_path.stat().st_size == 0: writer.writeheader()
                writer.writerow({"checkpoint": generation, "elapsed_seconds": int(time.monotonic() - start), "tests_completed": evaluated_tests, **{m: evaluation.metrics.get(m, "0.00") for m in METRICS}})
        _log(log, f"[{backend.name}] checkpoint {generation}: tests={evaluated_tests} SCORE={evaluation.metrics.get('SCORE', '0.00')}\n")
    if generation == 0: raise RuntimeError("campaign completed no generations")
    if deadline is not None and time.monotonic() >= deadline: _log(log, "Time budget exhausted, stopping fuzzing.\n")
    elapsed = int(time.monotonic() - start)
    _log(log, f"Total time = {elapsed // 3600} h {(elapsed % 3600) // 60} m {elapsed % 60} s.\n")
    _log(log, f"SemEvoFuzz campaign completed: dut={backend.name}, checkpoints={generation}, generations={generation}\n")
    if last_result is not None:
        import shutil
        shutil.copy2(log, Path(last_result) / "campaign.log")
