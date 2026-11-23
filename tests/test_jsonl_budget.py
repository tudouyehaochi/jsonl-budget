import json
from pathlib import Path
import subprocess
import sys
import unittest

from jsonl_budget import load_rates, summarize


ROOT = Path(__file__).resolve().parents[1]
USAGE = ROOT / "examples" / "usage.jsonl"
RATES = ROOT / "examples" / "rates.json"


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.rates = load_rates(RATES.read_text(encoding="utf-8"))

    def test_sample_totals_and_per_model_costs(self):
        with USAGE.open(encoding="utf-8") as lines:
            report = summarize(lines, self.rates)
        self.assertEqual(
            report["totals"],
            {
                "records": 3, "input_tokens": 19000, "output_tokens": 1600,
                "cost_usd": "0.00797",
            },
        )
        self.assertEqual(report["models"]["demo-a"]["cost_usd"], "0.00692")
        self.assertEqual(report["models"]["demo-b"]["cost_usd"], "0.00105")

    def test_blank_input(self):
        self.assertEqual(summarize(["", " \t\n"], self.rates), {
            "models": {},
            "totals": {"records": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": "0"},
        })

    def test_unused_rates_extra_fields_and_zero_cost(self):
        rates = load_rates(
            '{"a":{"input_usd_per_million":"0","output_usd_per_million":0},'
            '"b":{"input_usd_per_million":1,"output_usd_per_million":2}}'
        )
        report = summarize(
            ['{"model":"a","input_tokens":3,"output_tokens":2,"request_id":"demo"}'],
            rates,
        )
        self.assertEqual(list(report["models"]), ["a"])
        self.assertEqual(report["totals"]["cost_usd"], "0")

    def test_precision_below_one_cent_and_large_counts(self):
        rates = load_rates(
            '{"x":{"input_usd_per_million":"999999999999.999999999999",'
            '"output_usd_per_million":"0.000000000001"}}'
        )
        report = summarize(
            ['{"model":"x","input_tokens":100000000000000000000000000000000000000,'
             '"output_tokens":1}'], rates,
        )
        self.assertEqual(
            report["totals"]["cost_usd"],
            "99999999999999999999999900000000000000000000.000000000000000001",
        )

    def test_invalid_counts_include_physical_line_number(self):
        for count in ("true", "false", "-1", "null", "1.0", '"1"'):
            with self.subTest(count=count), self.assertRaisesRegex(
                ValueError, "line 2: input_tokens must be a nonnegative JSON integer",
            ):
                summarize(
                    ["\n", '{"model":"demo-a","input_tokens":' + count + ',"output_tokens":0}'],
                    self.rates,
                )

    def test_invalid_json_records_or_unknown_model(self):
        for line, expected in (
            ("{", "line 1:"),
            ("[]", "expected a JSON object"),
            ('{"model":"missing","input_tokens":0,"output_tokens":0}', "unknown model"),
            ('{"model":"demo-a","input_tokens":0}', "output_tokens"),
            ('{"model":"demo-a","input_tokens":0,"output_tokens":NaN}', "invalid JSON constant"),
            ('{"model":"demo-a","input_tokens":0,"input_tokens":1}', "duplicate JSON key"),
        ):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, expected):
                summarize([line], self.rates)

    def test_rate_validation(self):
        for rate in ('"-1"', "true", '"1e-7"', '"0.1234567890123"', "NaN"):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                load_rates('{"x":{"input_usd_per_million":' + rate + ',"output_usd_per_million":0}}')
        with self.assertRaisesRegex(ValueError, "must have exactly"):
            load_rates('{"x":{"input_usd_per_million":"2"}}')

    def test_cli_file_and_stdin_have_identical_json(self):
        command = [sys.executable, str(ROOT / "jsonl_budget.py"), "--rates", str(RATES)]
        from_file = subprocess.run(command + [str(USAGE)], capture_output=True, check=True)
        from_stdin = subprocess.run(
            command + ["-"], input=USAGE.read_bytes(), capture_output=True, check=True,
        )
        self.assertEqual(from_file.stdout, from_stdin.stdout)
        self.assertEqual(json.loads(from_file.stdout)["totals"]["cost_usd"], "0.00797")

    def test_cli_invalid_line_returns_no_partial_report(self):
        command = [sys.executable, str(ROOT / "jsonl_budget.py"), "--rates", str(RATES), "-"]
        proc = subprocess.run(command, input=USAGE.read_bytes() + b'{}\n', capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")
        self.assertIn(b"line 4:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
