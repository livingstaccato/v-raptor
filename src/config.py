# src/config.py
"""
Configuration loader for v-raptor.

This module loads configuration from config.json instead of hardcoding values.
This prevents code injection vulnerabilities from user input being written to Python files.
"""

from .config_schema import load_config

# Load configuration from JSON
_config = load_config()

# Export as module-level attributes for backwards compatibility
SCANNER_LLM_PROVIDER = _config.scanner_llm_provider
SCANNER_LLAMA_CPP_MODEL_PATH = _config.scanner_llama_cpp_model_path
SCANNER_OLLAMA_MODEL = _config.scanner_ollama_model
SCANNER_OLLAMA_URL = _config.scanner_ollama_url
SCANNER_GEMINI_MODEL = _config.scanner_gemini_model

PATCHER_LLM_PROVIDER = _config.patcher_llm_provider
PATCHER_LLAMA_CPP_MODEL_PATH = _config.patcher_llama_cpp_model_path
PATCHER_OLLAMA_MODEL = _config.patcher_ollama_model
PATCHER_OLLAMA_URL = _config.patcher_ollama_url
PATCHER_GEMINI_MODEL = _config.patcher_gemini_model

LLM_TIMEOUT = _config.llm_timeout

DATABASE_URL = _config.database_url

GITLEAKS_PATH = _config.gitleaks_path
SEMGREP_PATH = _config.semgrep_path
BANDIT_PATH = _config.bandit_path


def get_config():
    """Get the configuration object.

    Returns:
        VRaptorConfig: The current configuration
    """
    return _config


def reload_config():
    """Reload configuration from config.json.

    This updates all module-level variables with new values.
    """
    global _config, SCANNER_LLM_PROVIDER, SCANNER_LLAMA_CPP_MODEL_PATH
    global SCANNER_OLLAMA_MODEL, SCANNER_OLLAMA_URL, SCANNER_GEMINI_MODEL
    global PATCHER_LLM_PROVIDER, PATCHER_LLAMA_CPP_MODEL_PATH
    global PATCHER_OLLAMA_MODEL, PATCHER_OLLAMA_URL, PATCHER_GEMINI_MODEL
    global LLM_TIMEOUT, DATABASE_URL
    global GITLEAKS_PATH, SEMGREP_PATH, BANDIT_PATH

    _config = load_config()

    SCANNER_LLM_PROVIDER = _config.scanner_llm_provider
    SCANNER_LLAMA_CPP_MODEL_PATH = _config.scanner_llama_cpp_model_path
    SCANNER_OLLAMA_MODEL = _config.scanner_ollama_model
    SCANNER_OLLAMA_URL = _config.scanner_ollama_url
    SCANNER_GEMINI_MODEL = _config.scanner_gemini_model

    PATCHER_LLM_PROVIDER = _config.patcher_llm_provider
    PATCHER_LLAMA_CPP_MODEL_PATH = _config.patcher_llama_cpp_model_path
    PATCHER_OLLAMA_MODEL = _config.patcher_ollama_model
    PATCHER_OLLAMA_URL = _config.patcher_ollama_url
    PATCHER_GEMINI_MODEL = _config.patcher_gemini_model

    LLM_TIMEOUT = _config.llm_timeout
    DATABASE_URL = _config.database_url
    GITLEAKS_PATH = _config.gitleaks_path
    SEMGREP_PATH = _config.semgrep_path
    BANDIT_PATH = _config.bandit_path
