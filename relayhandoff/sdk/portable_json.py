"""relayhandoff/1 portable JSON domain. No implicit coercion or tagged values."""
import math
MAX_SAFE_NUMBER = 9007199254740991
MAX_DEPTH = 64

def validate(value, depth=0):
    if depth > MAX_DEPTH: raise ValueError('json_depth_exceeded')
    if value is None or type(value) is bool: return value
    if type(value) in (int,float):
        if type(value) is float and not math.isfinite(value): raise ValueError('json_non_finite_number')
        if abs(value) > MAX_SAFE_NUMBER: raise ValueError('json_number_out_of_range')
        return value
    if type(value) is str:
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value): raise ValueError('json_invalid_unicode')
        return value
    if type(value) is list:
        for item in value: validate(item,depth+1)
        return value
    if type(value) is dict:
        for key,item in value.items():
            if type(key) is not str: raise ValueError('json_non_string_key')
            validate(key,depth+1);validate(item,depth+1)
        return value
    raise ValueError('json_unsupported_type')
