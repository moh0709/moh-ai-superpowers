import unittest
from frontier.runtime.score import benchmark,promotion_screen


def make_records(n=40,reps=3,base_success=0.5,candidate_success=0.5,cost=1.0):
    records = []
    for task in range(n):
        for rep in range(reps):
            records += [dict(task_id=f'T-{task:03}',trial_index=rep,arm='baseline',success=(task/n < base_success),cost_usd=cost,safety_violation=False),
                        dict(task_id=f'T-{task:03}',trial_index=rep,arm='candidate',success=(task/n < candidate_success),cost_usd=cost,safety_violation=False)]
    return records

class BenchmarkTests(unittest.TestCase):
    def test_equal_success(self):
        s=benchmark(make_records()); self.assertEqual(s.absolute_gain_pp,0.0)
    def test_absolute_gain_pp(self):
        s=benchmark(make_records(base_success=0.5,candidate_success=.625))
        self.assertAlmostEqual(s.absolute_gain_pp,12.5)
    def test_repeated_runs_not_independent_tasks(self):
        s=benchmark(make_records(n=40,reps=3))
        self.assertEqual(s.tasks,40);self.assertEqual(s.repetitions,3)
    def test_unpaired_arms_rejected(self):
        r=make_records();r.pop();
        with self.assertRaises(ValueError):benchmark(r)
    def test_negative_cost_rejected(self):
        r=make_records();r[0]['cost_usd']=-1
        with self.assertRaises(ValueError):benchmark(r)
    def test_duplicate_trial_not_counted_as_new_replicate(self):
        r=make_records()
        r[0]=dict(r[2])
        with self.assertRaises(ValueError): benchmark(r)
    def test_invalid_result_rejected(self):
        r=make_records();r[0]['success']='yes'
        with self.assertRaises(ValueError):benchmark(r)
    def test_insufficient_task_sample(self):
        s=benchmark(make_records(n=10,reps=3,base_success=.3,candidate_success=.8))
        self.assertEqual(promotion_screen(s,independent_holdout=True,signed_review=True),'INSUFFICIENT_SAMPLE')
    def test_holdout_required(self):
        s=benchmark(make_records(base_success=.5,candidate_success=.9))
        self.assertEqual(promotion_screen(s,signed_review=True),'BLOCKED_HOLDOUT')
    def test_review_required(self):
        s=benchmark(make_records(base_success=.5,candidate_success=.9))
        self.assertEqual(promotion_screen(s,independent_holdout=True),'NEEDS_HUMAN_REVIEW')
    def test_no_improvement_not_promotable(self):
        s=benchmark(make_records())
        self.assertEqual(promotion_screen(s,independent_holdout=True,signed_review=True),'INCONCLUSIVE_OR_REGRESSION')
    def test_clear_gain_eligible_for_canary_only(self):
        s=benchmark(make_records(base_success=.4,candidate_success=.8))
        self.assertEqual(promotion_screen(s,independent_holdout=True,signed_review=True),'ELIGIBLE_FOR_CONTROLLED_CANARY')
    def test_safety_overrides_performance(self):
        r=make_records(base_success=.4,candidate_success=.8);r[1]['safety_violation']=True
        s=benchmark(r)
        self.assertEqual(promotion_screen(s,independent_holdout=True,signed_review=True),'REJECT_SAFETY')
    def test_cost_per_verified_task(self):
        s=benchmark(make_records(base_success=.5,candidate_success=.5,cost=1))
        self.assertAlmostEqual(s.baseline_cost_per_success,2.0)
    def test_no_success_cost_is_none(self):
        s=benchmark(make_records(base_success=0,candidate_success=0))
        self.assertIsNone(s.candidate_cost_per_success)

if __name__=='__main__':unittest.main()
