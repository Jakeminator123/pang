"""
Cost tracking for v0 API usage.
Estimates and tracks costs for v0 Platform API calls.
"""

from typing import Optional, Dict, Any
from datetime import datetime

# v0 Platform API pricing per 1M tokens (from v0.dev documentation)
# Note: These are estimates. Actual costs may vary based on usage.
V0_PRICING = {
    "v0-1.5-md": {"input": 1.50, "output": 7.50},  # $1.50/$7.50 per 1M tokens
    "v0-1.5-lg": {"input": 7.50, "output": 37.50},  # $7.50/$37.50 per 1M tokens
    "v0-1.0-md": {"input": 3.00, "output": 15.00},  # $3.00/$15.00 per 1M tokens
}

DEFAULT_MODEL = "v0-1.5-md"
ESTIMATED_COMPLETION_TOKENS = 3500  # Average tokens for a React component


def estimate_prompt_tokens(text: str) -> int:
    """
    Rough estimation: ~4 characters per token.
    This is a simple heuristic - actual tokenization may vary.
    """
    return len(text) // 4


def estimate_v0_cost(
    prompt: str,
    model: str = DEFAULT_MODEL,
    estimated_completion_tokens: int = ESTIMATED_COMPLETION_TOKENS,
) -> Dict[str, Any]:
    """
    Estimate cost for v0 API call based on prompt length.

    Args:
        prompt: User prompt text
        model: Model name
        estimated_completion_tokens: Estimated completion tokens

    Returns:
        Dict with estimated tokens and cost in USD
    """
    prompt_tokens = estimate_prompt_tokens(prompt)
    pricing = V0_PRICING.get(model, V0_PRICING[DEFAULT_MODEL])

    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (estimated_completion_tokens / 1_000_000) * pricing["output"]
    total_cost_usd = input_cost + output_cost

    return {
        "estimated_prompt_tokens": prompt_tokens,
        "estimated_completion_tokens": estimated_completion_tokens,
        "estimated_total_tokens": prompt_tokens + estimated_completion_tokens,
        "estimated_cost_usd": round(total_cost_usd, 6),
        "model": model,
        "timestamp": datetime.now().isoformat(),
    }


def create_cost_entry(
    estimated_cost: Dict[str, Any],
    actual_usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a cost entry combining estimated and actual costs.

    Args:
        estimated_cost: Estimated cost dict from estimate_v0_cost()
        actual_usage: Actual usage from v0 API (optional)

    Returns:
        Combined cost entry
    """
    entry = {
        "estimated": estimated_cost,
        "actual": actual_usage,
        "generated_at": datetime.now().isoformat(),
    }

    # Calculate difference if actual is available
    if actual_usage and "actual_cost_usd" in actual_usage:
        estimated = estimated_cost.get("estimated_cost_usd", 0)
        actual = actual_usage.get("actual_cost_usd", 0)
        entry["difference_usd"] = round(actual - estimated, 6)
        entry["difference_percent"] = round(
            ((actual - estimated) / estimated * 100) if estimated > 0 else 0, 2
        )

    return entry
