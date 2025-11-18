"""Input validation for v-raptor web endpoints using Pydantic."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator, ValidationError


class RepositoryUrlInput(BaseModel):
    """Validate repository URL input."""

    repo_url: str = Field(..., min_length=1, max_length=500)

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        """Validate repository URL format and content."""
        v = v.strip()

        # Basic validation
        if not v:
            raise ValueError("Repository URL cannot be empty")

        # Must contain github.com (currently only GitHub supported)
        if "github.com" not in v.lower():
            raise ValueError("Only GitHub repositories are currently supported")

        # Check for common issues
        if " " in v:
            raise ValueError("Repository URL cannot contain spaces")

        # Check for potential injection attempts
        dangerous_chars = [";", "|", "&", "$", "`", "\n", "\r"]
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"Invalid character in repository URL: {char}")

        # Must use http/https protocol if protocol specified
        if "://" in v:
            if not (v.startswith("http://") or v.startswith("https://")):
                raise ValueError("Repository URL must use http:// or https://")

        return v


class RepositoryConfirmInput(BaseModel):
    """Validate repository confirmation input."""

    repo_url: str = Field(..., min_length=1, max_length=500)
    branch: str = Field(..., min_length=1, max_length=100)

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        """Validate repository URL."""
        # Reuse the validation from RepositoryUrlInput
        return RepositoryUrlInput(repo_url=v).repo_url

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, v: str) -> str:
        """Validate branch name."""
        v = v.strip()

        if not v:
            raise ValueError("Branch name cannot be empty")

        # Check length
        if len(v) > 100:
            raise ValueError("Branch name too long (max 100 characters)")

        # Check for dangerous characters
        dangerous_chars = [";", "|", "&", "$", "`", "\n", "\r", "\\"]
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"Invalid character in branch name: {char}")

        return v


class ScanConfigInput(BaseModel):
    """Validate scan configuration input."""

    repo_id: int = Field(..., gt=0)
    auto_patch: bool = Field(default=False)

    @field_validator("repo_id")
    @classmethod
    def validate_repo_id(cls, v: int) -> int:
        """Validate repository ID."""
        if v <= 0:
            raise ValueError("Repository ID must be positive")
        if v > 2147483647:  # Max int32
            raise ValueError("Repository ID too large")
        return v


class PeriodicScanInput(BaseModel):
    """Validate periodic scan configuration."""

    periodic_scan_enabled: bool = Field(default=False)
    periodic_scan_interval: int = Field(default=86400, ge=3600, le=604800)

    @field_validator("periodic_scan_interval")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        """Validate scan interval is reasonable."""
        # Minimum 1 hour (3600s), maximum 1 week (604800s)
        if v < 3600:
            raise ValueError("Scan interval must be at least 1 hour (3600 seconds)")
        if v > 604800:
            raise ValueError("Scan interval cannot exceed 1 week (604800 seconds)")
        return v


class CIScanInput(BaseModel):
    """Validate CI/CD webhook scan input."""

    repo_url: str = Field(..., min_length=1, max_length=500)
    commit_hash: Optional[str] = Field(default=None, max_length=40)

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        """Validate repository URL."""
        return RepositoryUrlInput(repo_url=v).repo_url

    @field_validator("commit_hash")
    @classmethod
    def validate_commit_hash(cls, v: Optional[str]) -> Optional[str]:
        """Validate commit hash format."""
        if v is None:
            return v

        v = v.strip()
        if not v:
            return None

        # Git commit hashes are 40 hex characters
        if len(v) not in [7, 40]:  # Short or full hash
            raise ValueError("Commit hash must be 7 or 40 characters")

        # Only hex characters allowed
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("Commit hash must contain only hexadecimal characters")

        return v.lower()


def validate_input(model_class: type[BaseModel], data: dict) -> tuple[bool, str, dict]:
    """Validate input data against a Pydantic model.

    Args:
        model_class: Pydantic model class to validate against
        data: Dictionary of input data

    Returns:
        Tuple of (success, error_message, validated_data)
        - success: True if validation passed
        - error_message: Error description if validation failed, empty string otherwise
        - validated_data: Validated data as dict if successful, empty dict otherwise
    """
    try:
        validated = model_class(**data)
        return True, "", validated.model_dump()
    except ValidationError as e:
        # Extract first error message for user-friendly display
        errors = e.errors()
        if errors:
            first_error = errors[0]
            field = first_error["loc"][0] if first_error["loc"] else "input"
            msg = first_error["msg"]
            error_msg = f"Invalid {field}: {msg}"
        else:
            error_msg = "Validation failed"
        return False, error_msg, {}
    except Exception as e:
        return False, f"Validation error: {str(e)}", {}
