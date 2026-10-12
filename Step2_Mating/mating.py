import random
from Utils.file_utils import write_log

log_path = "log.txt"

# def coverage_select(size: int, score: list) -> int:
#     total_score = sum(score)
#     prob = [s / total_score for s in score]
#     return random.choices(range(size), prob)[0]

# def random_select(size: int, idx_1: int) -> int:
#     idx_2 = random.choice(range(size))
#     while idx_2 == idx_1:
#         idx_2 = random.choice(range(size))
#     return idx_2

# def mating(population_size: int, coverage_score: list, num_pairs: int) -> list:
#     pairs = []
#     for i in range(num_pairs):
#         if coverage_score == []:
#             idx_1 = random_select(population_size, -1)
#         else:
#             idx_1 = coverage_select(population_size, coverage_score)
#         idx_2 = random_select(population_size, idx_1)
#         pairs.append([idx_1, idx_2])
    
#     if pairs != []:
#         write_log(log_path, f"Selected pairs: {pairs}.")
#         write_log(log_path, f"Step2 finished. Selected {len(pairs)} pairs.\n")

#     return pairs

def ranked_selection(size: int, coverage_score: list) -> int:
    sorted_indices = sorted(range(size), key = lambda i: coverage_score[i], reverse = True)
    probabilities = [0.0] * size
    total_rank = size * (size + 1) / 2
    for rank, idx in enumerate(sorted_indices, 1):
        probabilities[idx] = (size - rank + 1) / total_rank
    return random.choices(range(size), weights = probabilities)[0]

def random_selection(size: int, exclude_idx: int = None) -> int:
    available_indices = list(range(size))
    if exclude_idx is not None and exclude_idx in available_indices:
        available_indices.remove(exclude_idx)
    if not available_indices:
        return random.randint(0, size - 1)
    return random.choice(available_indices)

def mating(size: int, mating_pairs: int, duplicate: bool = True, coverage_score: list = None) -> list:
    pairs = []
    used_pairs = set()
    write_log(log_path, f"Mating - coverage_score: {coverage_score}\n")
    
    if duplicate:
        for _ in range(mating_pairs):
            if len(coverage_score) == 0:
                parent1 = random_selection(size)
            else:
                parent1 = ranked_selection(size, coverage_score)
            parent2 = random_selection(size, exclude_idx = parent1)
            pair = tuple(sorted((parent1, parent2)))
            pairs.append(list(pair))

    else:
        assert mating_pairs <= size * (size - 1) // 2, "Mating pairs exceed possible combinations."
        for _ in range(mating_pairs):
            while True:
                if len(coverage_score) == 0:
                    parent1 = random_selection(size)
                else:
                    parent1 = ranked_selection(size, coverage_score)
                parent2 = random_selection(size, exclude_idx = parent1)
                pair = tuple(sorted((parent1, parent2)))
                if pair not in used_pairs:
                    used_pairs.add(pair)
                    pairs.append(list(pair))
                    break

    if pairs:
        write_log(log_path, f"Step2 finished. Selected {len(pairs)} pairs.\n")

    return pairs