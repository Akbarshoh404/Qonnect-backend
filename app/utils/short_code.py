"""
Cryptographically secure short code generation
"""
import secrets
import string
from typing import Optional


ALPHABET = string.ascii_letters + string.digits  # 62 chars
CODE_LENGTH = 7  # 62^7 ≈ 3.5 billion combinations


def generate_short_code(length: int = CODE_LENGTH) -> str:
    """Generate a cryptographically random short code."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_unique_short_code(check_exists_fn, length: int = CODE_LENGTH, max_attempts: int = 10) -> Optional[str]:
    """
    Generate a unique short code by checking against existing codes.
    
    Args:
        check_exists_fn: Callable that returns True if a code already exists
        length: Length of the code
        max_attempts: Maximum number of attempts before raising
    
    Returns:
        A unique short code string
    
    Raises:
        RuntimeError: If unable to generate a unique code after max_attempts
    """
    for _ in range(max_attempts):
        code = generate_short_code(length)
        if not check_exists_fn(code):
            return code
    raise RuntimeError(f"Failed to generate unique short code after {max_attempts} attempts")
