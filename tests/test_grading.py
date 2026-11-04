import unittest
from decimal import Decimal

from app.grading import (
    GradingError,
    grade_exam,
    grade_reflection,
    grade_stdio,
    parse_nonnegative_decimal,
    plain_number,
)


class SharedNumberParsingTests(unittest.TestCase):
    def test_decimal_and_numeric_forms_keep_existing_precision(self):
        value = Decimal("0.12345678901234567890123456789")
        self.assertEqual(parse_nonnegative_decimal(value, "points"), value)
        self.assertEqual(parse_nonnegative_decimal(2, "points"), Decimal(2))
        self.assertEqual(parse_nonnegative_decimal(2.5, "points"), Decimal("2.5"))
        self.assertEqual(plain_number(Decimal("2")), 2)
        self.assertEqual(plain_number(Decimal("2.5")), 2.5)

    def test_json_number_mode_still_rejects_decimal_objects(self):
        with self.assertRaisesRegex(ValueError, "finite non-negative number"):
            parse_nonnegative_decimal(Decimal("1"), "points", allow_decimal=False)

    def test_invalid_numbers_keep_validation_and_range_errors(self):
        for value in (True, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite non-negative number"):
                    parse_nonnegative_decimal(value, "points")
        with self.assertRaisesRegex(ValueError, "supported numeric range"):
            parse_nonnegative_decimal(Decimal("1e1001"), "points")


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

    def test_zero_check_result_is_valid_when_total_is_zero(self):
        result = grade_reflection([], {"score": 0, "total_points": 0, "checks": []}, 0)
        self.assertEqual((result.score, result.total_points, result.results), (0, 0, []))

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

    def test_negative_configured_points_are_invalid_request(self):
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                [{"id": "field", "points": -1}],
                {"score": 0, "total_points": 0, "checks": []},
                0,
            )
        self.assertEqual(caught.exception.category, "INVALID_REQUEST")

    def test_score_cannot_exceed_total(self):
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications,
                self.payload(11, [self.check("field", True, 4), self.check("behavior", True, 6)]),
                10,
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

    def test_checks_must_be_a_list_and_each_result_must_have_valid_fields(self):
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications,
                {"score": 0, "total_points": 10, "checks": ()},
                10,
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

        for field, value in (("expected", object()), ("actual", (1, 2)), ("error", 3)):
            with self.subTest(field=field):
                check = self.check("field", False, 0)
                check[field] = value
                with self.assertRaises(GradingError) as caught:
                    grade_reflection(
                        self.specifications,
                        self.payload(0, [check, self.check("behavior", False, 0)]),
                        10,
                    )
                self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

        missing_id = self.check("field", False, 0)
        del missing_id["id"]
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications,
                self.payload(0, [missing_id, self.check("behavior", False, 0)]),
                10,
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

    def test_check_points_if_reported_must_match_configuration(self):
        check = dict(self.check("field", True, 4), points=5)
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications,
                self.payload(4, [check, self.check("behavior", False, 0)]),
                10,
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

    def test_total_mismatch_is_not_normalized_to_checks_sum(self):
        specs = [{"id": "field", "points": 40}, {"id": "behavior", "points": 50}]
        payload = {
            "score": 90,
            "total_points": 100,
            "checks": [self.check("field", True, 40), self.check("behavior", True, 50)],
        }
        with self.assertRaises(GradingError) as caught:
            grade_reflection(specs, payload, 100)
        self.assertEqual(caught.exception.category, "INVALID_REQUEST")

    def test_verdict_is_validated_and_infrastructure_stays_distinct(self):
        checks = [self.check("field", True, 4), self.check("behavior", True, 6)]
        with self.assertRaises(GradingError) as caught:
            grade_reflection(self.specifications, self.payload(10, checks), 10, verdict="WHAT")
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

        with self.assertRaises(GradingError) as caught:
            grade_reflection(self.specifications, None, 10, verdict="JUDGE_INFRA_ERROR")
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")

        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications,
                {"error_category": ["JUDGE_INFRA_ERROR"]},
                10,
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

    def test_ac_and_wa_verdicts_must_match_check_outcomes(self):
        failed = [self.check("field", False, 0), self.check("behavior", False, 0)]
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications, self.payload(0, failed), 10, verdict="AC"
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

        passed = [self.check("field", True, 4), self.check("behavior", True, 6)]
        with self.assertRaises(GradingError) as caught:
            grade_reflection(
                self.specifications, self.payload(10, passed), 10, verdict="WA"
            )
        self.assertEqual(caught.exception.category, "PROTOCOL_ERROR")

        for category in ("JUDGE_INFRA_ERROR", "PROTOCOL_ERROR", "JDK_NOT_FOUND", "INVALID_REQUEST"):
            with self.subTest(category=category):
                with self.assertRaises(GradingError) as caught:
                    grade_reflection(
                        self.specifications,
                        self.payload(0, [self.check("field", False, 0), self.check("behavior", False, 0)]),
                        10,
                        verdict=category,
                    )
                self.assertEqual(caught.exception.category, category)

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

    def test_zero_score_and_infrastructure_failure_is_not_scored(self):
        results = [dict(item, points_earned=0, passed=False) for item in self.results]
        result = grade_stdio(self.specifications, results, 5)
        self.assertEqual(result.score, 0)
        with self.assertRaises(GradingError) as caught:
            grade_stdio(self.specifications, self.results, 5, verdict="JUDGE_INFRA_ERROR")
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")
        with self.assertRaises(GradingError) as caught:
            grade_stdio(self.specifications, self.results, 5, force_zero=True)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")

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

    def test_result_points_are_not_repaired_when_they_conflict_with_passed(self):
        invalid = [dict(self.results[0], points_earned=0), self.results[1]]
        with self.assertRaises(GradingError) as caught:
            grade_stdio(self.specifications, invalid, 5)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")

    def test_infrastructure_error_category_on_test_is_not_graded_as_wa(self):
        failed = [dict(self.results[0], verdict="JUDGE_INFRA_ERROR", error_category="JUDGE_INFRA_ERROR"), self.results[1]]
        with self.assertRaises(GradingError) as caught:
            grade_stdio(self.specifications, failed, 5)
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

    def test_legacy_question_id_fallback_is_preserved(self):
        result = grade_exam([{"id": "legacy-q", "score": 1, "total_points": 2}])
        self.assertEqual(result.questions[0]["question_id"], "legacy-q")

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
