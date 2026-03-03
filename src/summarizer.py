"""AI summarization providers with fallback chain."""

import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class BaseProvider(ABC):
    """Interface for summarization providers."""

    name: str = ''

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider can be used right now."""

    @abstractmethod
    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        """Generate a summary. Returns the summary text."""


class GeminiProvider(BaseProvider):
    name = 'gemini'

    def is_available(self) -> bool:
        return bool(os.environ.get('GEMINI_API_KEY'))

    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        from google import genai

        client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        model = cfg.get('gemini_model', 'gemini-2.0-flash')
        full_prompt = f"{prompt}\n\n{transcript_text}"
        response = client.models.generate_content(model=model, contents=full_prompt)
        return response.text


class OllamaProvider(BaseProvider):
    name = 'ollama'

    def is_available(self) -> bool:
        base_url = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
        try:
            req = urllib.request.Request(f"{base_url}/api/tags", method='GET')
            urllib.request.urlopen(req, timeout=3)
            return True
        except Exception:
            return False

    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        base_url = cfg.get('ollama_url', 'http://localhost:11434')
        model = cfg.get('ollama_model', 'llama3.1')
        full_prompt = f"{prompt}\n\n{transcript_text}"

        payload = json.dumps({
            'model': model,
            'prompt': full_prompt,
            'stream': False,
        }).encode()

        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=300)
        data = json.loads(resp.read())
        return data['response']


class ClaudeCLIProvider(BaseProvider):
    name = 'claude_cli'

    def is_available(self) -> bool:
        return shutil.which('claude') is not None

    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        result = subprocess.run(
            ['claude', '-p', prompt, '--stdin'],
            input=transcript_text,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI failed: {result.stderr.strip()}")
        return result.stdout.strip()


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    'gemini': GeminiProvider,
    'ollama': OllamaProvider,
    'claude_cli': ClaudeCLIProvider,
}


def summarize(transcript_text: str, cfg: dict, emit_fn=None) -> tuple[str, str]:
    """Try each configured provider in order, return (summary_text, provider_name).

    Falls back to the next provider on failure, matching the pattern in fetch_transcript_auto.
    """
    provider_names = cfg.get('providers', ['gemini', 'ollama', 'claude_cli'])
    prompt = cfg.get('prompt', 'Summarize this transcript.')
    errors = []

    for name in provider_names:
        cls = PROVIDER_REGISTRY.get(name)
        if not cls:
            log.warning("Unknown summarization provider: %s", name)
            continue

        provider = cls()

        if not provider.is_available():
            log.info("Provider %s not available, skipping", name)
            if emit_fn:
                emit_fn('status', message=f'Provider {name} not available, skipping...')
            continue

        try:
            if emit_fn:
                emit_fn('status', message=f'Summarizing with {name}...')
            log.info("Attempting summarization with %s", name)
            summary = provider.summarize(transcript_text, prompt, cfg)
            log.info("Summarization succeeded with %s", name)
            return summary, name
        except Exception as e:
            log.warning("Provider %s failed: %s", name, e)
            errors.append(f"{name}: {e}")
            if emit_fn:
                emit_fn('status', message=f'Provider {name} failed, trying next...')

    raise RuntimeError(
        "All summarization providers failed:\n" +
        "\n".join(f"  - {err}" for err in errors)
    )
