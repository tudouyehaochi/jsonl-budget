# jsonl-budget

Estimate the cost of a stream of token-usage records. Bring your own USD rates; the tool runs locally and never looks up prices, sends data, or uses provider credentials.

This is an **AI-assisted** portfolio project. All bundled data, model names, and rates are **synthetic** and are not provider quotes.

## Run

Python 3.10+; no third-party dependencies.

```sh
python jsonl_budget.py examples/usage.jsonl --rates examples/rates.json
# Also accepts JSONL piped to standard input:
cat examples/usage.jsonl | python jsonl_budget.py - --rates examples/rates.json
# Tests
python -m unittest discover -s tests -v
```

A usage line looks like:

```json
{"model":"demo-a","input_tokens":12000,"output_tokens":1000}
```

For each exact, case-sensitive model ID, provide two per-million-token rates in a separate JSON file. Decimal strings are recommended:

```json
{"demo-a":{"input_usd_per_million":"0.40","output_usd_per_million":"1.20"}}
```

The output is stable JSON with record and token counts and exact decimal USD **strings** per model and in the grand total. It sums unrounded costs; the sample total is `"0.00797"`. Only models present in the usage records are reported. Blank lines and extra usage fields are allowed. Unknown models, missing counts, booleans, negative counts, and malformed JSON produce an error on stderr (exit code 2) and no partial report.

The calculation is `(input_tokens × input_rate + output_tokens × output_rate) / 1,000,000`. Rates must be nonnegative and support up to 12 integer and 12 fractional digits. The estimate does not include cache discounts, taxes, tiered billing, or other provider-specific charges. Active model count, not total line count, determines aggregate memory use.
