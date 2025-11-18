"""Configuration schema for v-raptor using Pydantic for type safety and validation."""

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class VRaptorConfig(BaseModel):
    """V-Raptor configuration with validation.

    This replaces the old config.py module to prevent code injection vulnerabilities.
    Configuration is loaded from config.json and can be overridden by environment variables.
    """

    # Scanner Model Configuration
    scanner_llm_provider: Literal["gemini", "llama.cpp", "ollama"] = Field(
        default="ollama", description="LLM provider for scanning"
    )
    scanner_llama_cpp_model_path: str = Field(
        default="/path/to/your/scanner/model.gguf",
        description="Path to llama.cpp model for scanning",
    )
    scanner_ollama_model: str = Field(
        default="gemma3:latest", description="Ollama model name for scanning"
    )
    scanner_ollama_url: str = Field(
        default="http://localhost:11434", description="Ollama server URL for scanning"
    )
    scanner_gemini_model: str = Field(
        default="gemini-1.5-flash-latest", description="Gemini model name for scanning"
    )

    # Patcher Model Configuration
    patcher_llm_provider: Literal["gemini", "llama.cpp", "ollama"] = Field(
        default="ollama", description="LLM provider for patching"
    )
    patcher_llama_cpp_model_path: str = Field(
        default="/path/to/your/patcher/model.gguf",
        description="Path to llama.cpp model for patching",
    )
    patcher_ollama_model: str = Field(
        default="gemma3:latest", description="Ollama model name for patching"
    )
    patcher_ollama_url: str = Field(
        default="http://localhost:11434", description="Ollama server URL for patching"
    )
    patcher_gemini_model: str = Field(
        default="gemini-1.5-pro-latest", description="Gemini model name for patching"
    )

    # LLM Timeout
    llm_timeout: int = Field(
        default=60, gt=0, description="LLM request timeout in seconds"
    )

    # Database Configuration
    database_url: str = Field(
        default="sqlite:///v-raptor.db", description="Database connection URL"
    )

    # Tool Paths
    gitleaks_path: str = Field(
        default="gitleaks", description="Path to gitleaks binary"
    )
    semgrep_path: str = Field(default="semgrep", description="Path to semgrep binary")
    bandit_path: str = Field(default="bandit", description="Path to bandit binary")

    @field_validator("llm_timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Ensure timeout is positive."""
        if v <= 0:
            raise ValueError("llm_timeout must be positive")
        return v

    @field_validator("scanner_ollama_url", "patcher_ollama_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Basic URL validation."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    model_config = {
        "frozen": False,  # Allow updates
        "validate_assignment": True,  # Validate on assignment
    }


def load_config(config_path: str = "config.json") -> VRaptorConfig:
    """Load configuration from JSON file.

    Args:
        config_path: Path to JSON configuration file

    Returns:
        VRaptorConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    import json
    from pathlib import Path

    # Try multiple locations
    possible_paths = [
        Path(config_path),
        Path(__file__).parent.parent / config_path,
        Path(__file__).parent / config_path,
    ]

    for path in possible_paths:
        if path.exists():
            with open(str(path), "r") as f:
                config_data = json.load(f)
            return VRaptorConfig(**config_data)

    # If no config file found, use defaults
    return VRaptorConfig()


def save_config(config: VRaptorConfig, config_path: str = "config.json") -> None:
    """Save configuration to JSON file.

    Args:
        config: VRaptorConfig instance to save
        config_path: Path to JSON configuration file
    """
    import json
    from pathlib import Path

    # Save to project root
    target_path = Path(__file__).parent.parent / config_path

    with open(target_path, "w") as f:
        json.dump(config.model_dump(), f, indent=2)
