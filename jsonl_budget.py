"""Estimate USD from reported token counts and explicit per-million rates."""

import argparse
import json
from decimal import Decimal, Inexact, localcontext
from pathlib import Path
import re
import sys
from typing import Iterable


FIELDS = ("input_tokens", "output_tokens")
RATE_FIELDS = ("input_usd_per_million", "output_usd_per_million")
RATE_PATTERN = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,12})?\Z")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def read_json(text, *, parse_float=Decimal):
    return json.loads(
        text, parse_float=parse_float, parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )


def parse_rate(value):
    if type(value) not in (str, int) or not RATE_PATTERN.fullmatch(str(value)):
        raise ValueError("rates must be nonnegative decimals with at most 12 digits on each side")
    return Decimal(value)


def load_rates(text):
    """Return model -> (input USD per million, output USD per million)."""
    # Validate the original number spelling before Decimal can normalize it
    # (for example, fixed-point 0.0000001 becomes 1E-7).
    rates = read_json(text, parse_float=str)
    if not isinstance(rates, dict) or not rates:
        raise ValueError("expected a nonempty JSON object keyed by model name")
    result = {}
    for model, entry in rates.items():
        if not model.strip():
            raise ValueError("rates contain an empty model name")
        if not isinstance(entry, dict) or set(entry) != set(RATE_FIELDS):
            raise ValueError(f"model {model!r} must have exactly {', '.join(RATE_FIELDS)}")
        try:
            result[model] = tuple(parse_rate(entry[field]) for field in RATE_FIELDS)
        except ValueError as exc:
            raise ValueError(f"model {model!r}: {exc}") from exc
    return result


def usd_text(value: Decimal) -> str:
    """Serialize in fixed point, never round to cents or emit a binary float."""
    formatted = format(value, "f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def summarize(lines: Iterable[str], rates: dict) -> dict:
    """Stream records while retaining only one aggregate for each seen model."""
    counts = {}
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = read_json(line)
            if not isinstance(entry, dict):
                raise ValueError("expected a JSON object")
            model = entry.get("model")
            if not isinstance(model, str) or not model.strip():
                raise ValueError("model must be a nonempty string")
            if model not in rates:
                raise ValueError(f"unknown model {model!r}; add it to the rates file")
            amounts = [entry.get(field) for field in FIELDS]
            for field, value in zip(FIELDS, amounts):
                if type(value) is not int or value < 0:
                    raise ValueError(f"{field} must be a nonnegative JSON integer")
        except ValueError as exc:
            raise ValueError(f"line {line_no}: {exc}") from exc

        row = counts.setdefault(model, [0, 0, 0])
        row[0] += 1
        row[1] += amounts[0]
        row[2] += amounts[1]

    totals = [sum(row[i] for row in counts.values()) for i in range(3)]
    # All rates have <=12 integer and <=12 fractional digits. 30 extra
    # digits beyond aggregate token count suffice through scaling by 1e6.
    # A trap makes inadvertent rounding an error rather than a wrong bill.
    with localcontext() as context:
        context.prec = max(40, (totals[1] + totals[2]).bit_length() + 30)
        context.traps[Inexact] = True
        by_model = {}
        total_usd = Decimal(0)
        for model, (records, inputs, outputs) in sorted(counts.items()):
            rate_in, rate_out = rates[model]
            cost = (inputs * rate_in + outputs * rate_out) / Decimal(1_000_000)
            by_model[model] = {
                "records": records, "input_tokens": inputs, "output_tokens": outputs,
                "cost_usd": usd_text(cost),
            }
            total_usd += cost
    return {
        "models": by_model,
        "totals": {
            "records": totals[0], "input_tokens": totals[1], "output_tokens": totals[2],
            "cost_usd": usd_text(total_usd),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", help="UTF-8 JSONL path or '-' for standard input")
    parser.add_argument("--rates", required=True, type=Path, help="UTF-8 JSON pricing file")
    args = parser.parse_args(argv)

    try:
        rates = load_rates(args.rates.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: rates: {exc}", file=sys.stderr)
        return 2

    try:
        if args.records == "-":
            report = summarize(sys.stdin, rates)
        else:
            with Path(args.records).open(encoding="utf-8") as stream:
                report = summarize(stream, rates)
    except (OSError, ValueError) as exc:
        print(f"error: records: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
