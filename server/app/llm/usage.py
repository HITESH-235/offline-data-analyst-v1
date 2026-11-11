"""Provider-reported token counts only. Never infer tokens from text length.

Details are subsets of input/output counts, not additional chargeable totals.
Unknown/malformed counters remain null, including responses without usage.
"""
from app.services.request_control import TOKEN_FIELDS, record_model_usage


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def report_usage(provider, response):
    response = _mapping(response)
    result = dict.fromkeys(TOKEN_FIELDS)
    if provider == 'ollama':
        result.update(input_tokens=_count(response.get('prompt_eval_count')),
                      output_tokens=_count(response.get('eval_count')),
                      cached_input_tokens=_count(response.get('prompt_eval_cached_count')))
        if result['input_tokens'] is not None and result['output_tokens'] is not None:
            result['total_tokens'] = result['input_tokens'] + result['output_tokens']
    result['source'] = 'provider' if any(v is not None for v in result.values()) else 'unavailable'
    record_model_usage(result)
    return result
