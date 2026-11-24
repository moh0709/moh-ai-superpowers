import unittest
from frontier.evals.compare_gates import run


class BaselineComparison(unittest.TestCase):
    def test_candidate_handles_all_targeted_regression_cases(self):
        result = run()
        self.assertEqual(result['cases'], 14)
        self.assertEqual(result['v2_2_correct'], 14)
        self.assertEqual(result['v2_2_exceptions'], 0)

    def test_archived_baseline_behavior_is_reproducible(self):
        result = run()
        self.assertLess(result['v2_1_correct'], result['v2_2_correct'])


if __name__=='__main__':unittest.main()
