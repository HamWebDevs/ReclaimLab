"""Finite, bounded JSON numbers, including on Python versions without integer limits."""
import json
import math


def loads(payload, **options):
    def invalid(value):
        raise ValueError('JSON numbers must be finite and bounded')
    def integer(value):
        if len(value.lstrip('-')) > 128: return invalid(value)
        return int(value)
    def number(value):
        if len(value) > 256: return invalid(value)
        result = float(value)
        return result if math.isfinite(result) else invalid(value)
    try:
        return json.loads(payload, parse_constant=invalid, parse_int=integer, parse_float=number, **options)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('Invalid or excessively nested JSON input') from exc
