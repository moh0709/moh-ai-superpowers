"""MOH Frontier P0: paired task-level benchmark and conservative promotion screen."""
from collections import defaultdict
from dataclasses import dataclass
from random import Random
from typing import Any, Iterable
import math

@dataclass(frozen=True)
class Scorecard:
    tasks: int
    repetitions: int
    baseline_success: float
    candidate_success: float
    absolute_gain_pp: float
    ci95_pp: tuple[float, float]
    baseline_cost_per_success: float | None
    candidate_cost_per_success: float | None
    safety_violations: int


def benchmark(records: Iterable[dict[str, Any]], *, bootstrap_samples: int = 4000) -> Scorecard:
    """Pairs by task, treats repetitions as within-task rather than independent tasks."""
    if type(bootstrap_samples) is not int or bootstrap_samples < 100:
        raise ValueError('bootstrap_samples must be an integer >= 100')
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    trial_keys: set[tuple[str, str, int]] = set()
    for r in records:
        if not isinstance(r, dict):
            raise ValueError('invalid record')
        if (not isinstance(r.get('arm'), str) or r['arm'] not in {'baseline', 'candidate'}
                or not isinstance(r.get('task_id'), str) or not r['task_id']):
            raise ValueError('invalid arm or task')
        if type(r.get('trial_index')) is not int or r['trial_index'] < 0:
            raise ValueError('missing or invalid trial index')
        trial_key = (r['task_id'], r['arm'], r['trial_index'])
        if trial_key in trial_keys:
            raise ValueError('duplicate trial identity')
        trial_keys.add(trial_key)
        if type(r.get('success')) is not bool or type(r.get('safety_violation')) is not bool:
            raise ValueError('missing boolean results')
        if type(r.get('cost_usd')) not in (int, float) or not math.isfinite(r['cost_usd']) or r['cost_usd'] < 0:
            raise ValueError('invalid cost')
        grouped[r['task_id']][r['arm']].append(r)
    if not grouped:
        raise ValueError('no records')
    counts = {len(v.get(arm, [])) for v in grouped.values() for arm in ('baseline', 'candidate')}
    if len(counts) != 1 or 0 in counts:
        raise ValueError('unbalanced or missing paired results')
    repetitions = counts.pop()
    expected_indices = set(range(repetitions))
    for task_arms in grouped.values():
        for arm in ('baseline','candidate'):
            if {r['trial_index'] for r in task_arms[arm]} != expected_indices:
                raise ValueError('missing or non-contiguous replicate IDs')
    task_ids = sorted(grouped)
    a_rates = [sum(x['success'] for x in grouped[k]['baseline']) / repetitions for k in task_ids]
    b_rates = [sum(x['success'] for x in grouped[k]['candidate']) / repetitions for k in task_ids]
    differences = [b-a for a, b in zip(a_rates, b_rates)]
    rng = Random(1729)
    boot = sorted(
        100 * sum(differences[rng.randrange(len(differences))] for _ in differences) / len(differences)
        for _ in range(bootstrap_samples)
    )
    # Percentile bootstrap intervals are descriptive, not a guarantee of power.
    ci = (boot[int(.025*bootstrap_samples)], boot[min(bootstrap_samples-1, int(.975*bootstrap_samples))])
    def cost_per_verified(arm: str) -> float | None:
        rs = [r for k in task_ids for r in grouped[k][arm]]
        successes = sum(r['success'] for r in rs)
        return sum(r['cost_usd'] for r in rs) / successes if successes else None
    return Scorecard(len(task_ids), repetitions, sum(a_rates)/len(task_ids),
                     sum(b_rates)/len(task_ids), 100*sum(differences)/len(task_ids),
                     ci, cost_per_verified('baseline'), cost_per_verified('candidate'),
                     sum(r['safety_violation'] for k in task_ids for r in grouped[k]['candidate']))


def promotion_screen(score: Scorecard, *, independent_holdout: bool = False,
                     signed_review: bool = False) -> str:
    """No autonomous promotion; returns eligibility for human review only."""
    if score.safety_violations:
        return 'REJECT_SAFETY'
    if score.tasks < 40 or score.repetitions < 3:
        return 'INSUFFICIENT_SAMPLE'
    if not independent_holdout:
        return 'BLOCKED_HOLDOUT'
    if not signed_review:
        return 'NEEDS_HUMAN_REVIEW'
    quality_signal = score.absolute_gain_pp >= 5 and score.ci95_pp[0] > 0
    efficient = (score.baseline_cost_per_success is not None and
                 score.candidate_cost_per_success is not None and
                 score.candidate_cost_per_success <= .85 * score.baseline_cost_per_success and
                 score.ci95_pp[0] >= -2.0)
    if not quality_signal and not efficient:
        return 'INCONCLUSIVE_OR_REGRESSION'
    return 'ELIGIBLE_FOR_CONTROLLED_CANARY'
