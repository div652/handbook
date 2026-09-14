import math
import unittest

from scripts.benchmark_progress import reward


def result_with_reward(value: object) -> dict:
    return {"verifier_result": {"rewards": {"reward": value}}}


class RewardTests(unittest.TestCase):
    def test_accepts_finite_reward_in_closed_unit_interval(self) -> None:
        for value in (0, 0.25, 1):
            with self.subTest(value=value):
                self.assertEqual(reward(result_with_reward(value)), float(value))

    def test_rejects_invalid_reward(self) -> None:
        for value in (True, False, -0.01, 1.01, math.nan, math.inf, -math.inf, "1"):
            with self.subTest(value=value):
                self.assertIsNone(reward(result_with_reward(value)))


if __name__ == "__main__":
    unittest.main()
