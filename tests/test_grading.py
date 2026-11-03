import unittest
from decimal import Decimal

from app.grading import GradingError, grade_exam, grade_reflection, grade_stdio


class ReflectionGradingTests(unittest.TestCase):
    def setUp(self):
        self.specifications = [
            {"id": "field", "points": 4},
            {"id": "behavior", "points": 6},
        ]

    @staticmethod
    def check(check_id, passed, points_earned):
        return {
            "id": check_id,
            "passed": passed,
            "points_earned": points_earned,
            "expected": None,
            "actual": None,
            "error": None,
        }

    def payload(self, score, checks):
        return {"score": score, "total_points": 10, "checks": checks}

    def test_all_checks_pass(self):
        result = grade_reflection(
            self.specifications,
            self.payload(10, [self.check("field", True, 4), self.check("behavior", True, 6)]),
            10,
        )
        self.assertEqual((result.score, result.total_points), (10, 10))
        self.assertEqual([check["id"] for check in result.results], ["field", "behavior"])

    def test_partial_check_credit_is_summed(self):
        result = grade_reflection(
            self.specifications,
            self.payload(2.5, [self.check("field", False, 0), self.check("behavior", True, 2.5)]),
            10,
        )
        self.assertEqual(result.score, 2.5)

    def test_zero_score(self):
        result = grade_reflection(
            self.specifications,
            self.payload(0, [self.check("field", False, 0), self.check("behavior", False, 0)]),
            10,
        )
        self.assertEqual(result.score, 0)

    def test_duplicate_result_check_id_is_protocol_error(self):
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications,
                self.payload(4, [self.check("field", True, 4), self.check("field", False, 0)]),
                10,
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

    def test_duplicate_configured_check_id_is_invalid_request(self):
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                [{"id": "same", "points": 1}, {"id": "same", "points": 1}],
                {"score": 0, "total_points": 2, "checks": []},
                2,
            )
        self.assertEqual(caught.exception.category, "INVALID_REQUEST")

    def test_negative_or_excessive_points_are_protocol_errors(self):
        for earned in (-1, 4.01):
            with self.subTest(earned=earned):
                with self.assertRaises(GradingError) as caught:
                    grade_reflection(
                        self.specifications,
                        self.payload(
                            earned,
                            [self.check("field", True, earned), self.check("behavior", False, 0)],
                        ),
                        10,
                    )
                self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

    def test_declared_score_must_match_check_points(self):
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications,
                self.payload(9, [self.check("field", True, 4), self.check("behavior", False, 0)]),
                10,
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

    def test_configured_total_must_match_check_points(self):
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                [{"id": "field", "points": 4}],
                {"score": 0, "total_points": 5, "checks": [self.check("field", False, 0)]},
                5,
            )
        self.assertEqual(caught.exception.category, "INVALID_REQUEST")

    def test_decimal_points_sum_without_rounding(self):
        points = Decimal("0.12345678901234567890123456789")
        total = Decimal("0.24691357802469135780246913578")
        checks = [self.check("first", True, points), self.check("second", True, points)]
        result = grade_reflection(
            [{"id": "first", "points": points}, {"id": "second", "points": points}],
            {"score": total, "total_points": total, "checks": checks},
            total,
        )
        self.assertEqual(result.score, float(total))


class StdioGradingTests(unittest.TestCase):
    def setUp(self):
        self.specifications = [
            {"id": "visible", "points": 2},
            {"id": "hidden", "points": 3},
        ]
        self.results = [
            {"id": "visible", "points": 2, "points_earned": 2, "passed": True},
            {"id": "hidden", "points": 3, "points_earned": 0, "passed": False},
        ]

    def test_all_tests_pass(self):
        results = [dict(item, points_earned=item["points"], passed=True) for item in self.results]
        result = grade_stdio(self.specifications, results, 5)
        self.assertEqual((result.score, result.total_points), (5, 5))

    def test_partial_test_results_are_summed(self):
        result = grade_stdio(self.specifications, self.results, 5)
        self.assertEqual((result.score, result.total_points), (2, 5))
        self.assertEqual(len(result.results), 2)

    def test_zero_score_and_infrastructure_zeroing(self):
        results = [dict(item, points_earned=0, passed=False) for item in self.results]
        result = grade_stdio(self.specifications, results, 5)
        self.assertEqual(result.score, 0)
        awarded_then_failed = grade_stdio(self.specifications, self.results, 5, force_zero=True)
        self.assertEqual(awarded_then_failed.score, 0)

    def test_duplicate_test_result_id_is_infrastructure_error(self):
        duplicate = [self.results[0], dict(self.results[1], id="visible")]
        with self.assertRaises(GradingError) as caught:
            grade_stdio(self.specifications, duplicate, 5)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")

    def test_result_points_cannot_exceed_configuration(self):
        invalid = [dict(self.results[0], points_earned=2.1), self.results[1]]
        with self.assertRaises(GradingError) as caught:
            grade_stdio(self.specifications, invalid, 5)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")


class ExamGradingTests(unittest.TestCase):
    def test_multiple_question_scores_are_aggregated(self):
        result = grade_exam(
            [
                {"question_id": "q1", "score": 7.5, "total_points": 10},
                {"question_id": "q2", "score": 3, "total_points": 5},
            ]
        )
        self.assertEqual((result.score, result.total_points), (10.5, 15))
        self.assertEqual([item["question_id"] for item in result.questions], ["q1", "q2"])

    def test_question_score_cannot_exceed_configured_total(self):
        with self.assertRaises(GradingError) as caught:
            grade_exam([{"question_id": "q1", "score": 11, "total_points": 10}])
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")

    def test_duplicate_question_id_is_rejected(self):
        with self.assertRaises(GradingError) as caught:
            grade_exam(
                [
                    {"question_id": "q1", "score": 1, "total_points": 2},
                    {"question_id": "q1", "score": 1, "total_points": 2},
                ]
            )
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")


if __name__ == "__main__":
    unittest.main()
