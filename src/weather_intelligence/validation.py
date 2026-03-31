"""Input validation utilities for MCP tools."""

import re
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: str | None = None):
        self.field = field
        super().__init__(f"{field}: {message}" if field else message)


INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", "instruction_override", "CRITICAL"),
    (r"disregard\s+(all\s+)?(previous|prior)", "instruction_override", "CRITICAL"),
    (r"forget\s+(everything|all|your)\s+(instructions?|rules?|guidelines?)", "instruction_override", "CRITICAL"),
    (r"you\s+are\s+now\s+", "role_hijack", "HIGH"),
    (r"act\s+as\s+(if\s+you\s+are|a)\s+", "role_hijack", "HIGH"),
    (r"pretend\s+(to\s+be|you\s+are)\s+", "role_hijack", "HIGH"),
    (r"reveal\s+(your|the)\s+(api|secret|system)\s*(key|token|prompt)?", "secret_extraction", "CRITICAL"),
    (r"show\s+me\s+(your|the)\s+(system\s+)?prompt", "secret_extraction", "CRITICAL"),
    (r"what\s+(is|are)\s+your\s+(instructions?|rules?|guidelines?)", "secret_extraction", "HIGH"),
    (r"<\s*script\s*>", "xss_attempt", "HIGH"),
    (r"javascript\s*:", "xss_attempt", "HIGH"),
    (r"\{\{\s*[^}]+\s*\}\}", "template_injection", "MEDIUM"),
    (r"\$\{\s*[^}]+\s*\}", "template_injection", "MEDIUM"),
]


def check_prompt_injection(value: str) -> str | None:
    """
    Check for prompt injection patterns in input.
    
    Args:
        value: The input string to check
        
    Returns:
        None if no injection detected (allows chaining with `or`)
        
    Raises:
        ValidationError: If injection pattern detected
    """
    if not isinstance(value, str):
        return None
    
    value_lower = value.lower()
    
    for pattern, name, severity in INJECTION_PATTERNS:
        if re.search(pattern, value_lower, re.IGNORECASE):
            logger.warning(
                f"Prompt injection detected in input: "
                f"pattern={name} severity={severity} "
                f'preview="{value[:40]}..."'
            )
            raise ValidationError(
                f"Input rejected: potential prompt injection detected",
                field="input"
            )
    
    return None


class Validator:
    """Collection of validation functions."""

    @staticmethod
    def length(value: str, min_len: int = 0, max_len: int = 1000) -> str:
        """Validate string length."""
        if len(value) < min_len:
            raise ValidationError(f"Too short (min {min_len} chars)")
        if len(value) > max_len:
            raise ValidationError(f"Too long (max {max_len} chars)")
        return value

    @staticmethod
    def integer_range(value: int, min_val: int, max_val: int) -> int:
        """Validate integer is within range."""
        if not isinstance(value, int):
            raise ValidationError(f"Expected integer, got {type(value).__name__}")
        if value < min_val or value > max_val:
            raise ValidationError(f"Value must be between {min_val} and {max_val}")
        return value

    @staticmethod
    def sanitized_string(
        value: str,
        field: str = "value",
        max_len: int = 500,
        allow_newlines: bool = False,
    ) -> str:
        """Sanitize and validate a string."""
        if not isinstance(value, str):
            raise ValidationError(f"Expected string", field=field)
        
        value = value.strip()
        
        if not allow_newlines:
            value = " ".join(value.split())
        
        if len(value) > max_len:
            raise ValidationError(f"Too long (max {max_len} chars)", field=field)
        
        return value


def validate(**validators: Callable[[Any], Any]):
    """
    Decorator to validate tool arguments.
    
    Usage:
        @mcp.tool()
        @validate(city=lambda v: check_prompt_injection(v) or Validator.length(v, max_len=200))
        async def my_tool(city: str) -> dict:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for param_name, validator in validators.items():
                if param_name in kwargs:
                    try:
                        result = validator(kwargs[param_name])
                        if result is not None:
                            kwargs[param_name] = result
                    except ValidationError:
                        raise
                    except Exception as e:
                        raise ValidationError(str(e), field=param_name)
            return await func(*args, **kwargs)
        return wrapper
    return decorator
