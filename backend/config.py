"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Each council seat is overridable per run via an env var (the council-review
# CLI sets these from its --gpt/--gemini/--claude/--grok flags).
GPT_MODEL = os.getenv("COUNCIL_GPT_MODEL", "openai/gpt-5.1")
GEMINI_MODEL = os.getenv("COUNCIL_GEMINI_MODEL", "google/gemini-3.1-pro-preview")
CLAUDE_MODEL = os.getenv("COUNCIL_CLAUDE_MODEL", "anthropic/claude-sonnet-4.6")
GROK_MODEL = os.getenv("COUNCIL_GROK_MODEL", "x-ai/grok-4.3")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [GPT_MODEL, GEMINI_MODEL, CLAUDE_MODEL, GROK_MODEL]

# Chairman model - synthesizes final response (overridable per run)
CHAIRMAN_MODEL = os.getenv("COUNCIL_CHAIRMAN_MODEL", "google/gemini-3.1-pro-preview")

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"
