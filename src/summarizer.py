"""AI text-generation providers with fallback chain.

Used for both one-shot summarization and multi-turn chat. Providers implement
`generate(prompt, cfg)`; `summarize()` is a thin wrapper that also builds the
summarization prompt. `run_providers()` is the shared fallback loop.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class BaseProvider(ABC):
    """Interface for text-generation providers."""

    name: str = ''

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider can be used right now."""

    def get_setup_hint(self) -> str | None:
        """Return an actionable message when the provider is not available."""
        return None

    @abstractmethod
    def generate(self, prompt: str, cfg: dict) -> str:
        """Generate text from a fully-assembled prompt."""

    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        """Summarize transcript by concatenating prompt and transcript."""
        return self.generate(f"{prompt}\n\n{transcript_text}", cfg)


class GeminiProvider(BaseProvider):
    name = 'gemini'

    def is_available(self) -> bool:
        return bool(os.environ.get('GEMINI_API_KEY'))

    def get_setup_hint(self) -> str | None:
        if not os.environ.get('GEMINI_API_KEY'):
            return 'GEMINI_API_KEY not set. Add it to your .env file.'
        return None

    def generate(self, prompt: str, cfg: dict) -> str:
        from google import genai

        client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        model = cfg.get('gemini_model', 'gemini-2.0-flash')
        response = client.models.generate_content(model=model, contents=prompt)
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

    def get_setup_hint(self) -> str | None:
        return 'Ollama is not running. Start it or install from https://ollama.com'

    def generate(self, prompt: str, cfg: dict) -> str:
        base_url = cfg.get('ollama_url', 'http://localhost:11434')
        model = cfg.get('ollama_model', 'llama3.1')

        payload = json.dumps({
            'model': model,
            'prompt': prompt,
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


class ClaudeProxyProvider(BaseProvider):
    name = 'claude_proxy'

    def is_available(self) -> bool:
        proxy_url = self._get_proxy_url({})
        try:
            req = urllib.request.Request(f"{proxy_url}/health", method='GET')
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            return data.get('claude_available') is True
        except Exception:
            return False

    def get_setup_hint(self) -> str | None:
        return (
            'Claude-Proxy is not reachable. '
            'Ensure the claude-proxy container is running on the claude-proxy-net network.'
        )

    def generate(self, prompt: str, cfg: dict) -> str:
        proxy_url = self._get_proxy_url(cfg)
        payload = json.dumps({
            'prompt': prompt,
            'model': cfg.get('claude_model', 'sonnet'),
            'timeout': 300,
        }).encode()

        req = urllib.request.Request(
            f"{proxy_url}/generate",
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=330)
        data = json.loads(resp.read())

        if 'error' in data:
            raise RuntimeError(f"Claude-Proxy error: {data['error']}")

        return data['result']

    def _get_proxy_url(self, cfg: dict) -> str:
        return (
            cfg.get('claude_proxy_url')
            or os.environ.get('CLAUDE_PROXY_URL')
            or 'http://claude-proxy:9100'
        )


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    'gemini': GeminiProvider,
    'ollama': OllamaProvider,
    'claude_proxy': ClaudeProxyProvider,
}


def run_providers(prompt: str, cfg: dict, emit_fn=None) -> tuple[str, str]:
    """Try each configured provider in order, return (text, provider_name).

    Falls back to the next provider on failure. Shared by summarization and chat.
    """
    provider_names = cfg.get('providers', ['claude_proxy', 'gemini', 'ollama'])
    errors = []

    for name in provider_names:
        cls = PROVIDER_REGISTRY.get(name)
        if not cls:
            log.warning("Unknown provider: %s", name)
            continue

        provider = cls()

        if not provider.is_available():
            hint = provider.get_setup_hint()
            if hint:
                log.info("Provider %s not available: %s", name, hint)
                if emit_fn:
                    emit_fn('status', message=f'{hint}')
                errors.append(f"{name}: {hint}")
            else:
                log.info("Provider %s not available, skipping", name)
                if emit_fn:
                    emit_fn('status', message=f'Provider {name} not available, skipping...')
            continue

        try:
            if emit_fn:
                emit_fn('status', message=f'Generating with {name}...')
            log.info("Attempting generation with %s", name)
            text = provider.generate(prompt, cfg)
            log.info("Generation succeeded with %s", name)
            return text, name
        except Exception as e:
            log.warning("Provider %s failed: %s", name, e)
            errors.append(f"{name}: {e}")
            if emit_fn:
                emit_fn('status', message=f'Provider {name} failed, trying next...')

    raise RuntimeError(
        "All providers failed:\n" +
        "\n".join(f"  - {err}" for err in errors)
    )


def summarize(transcript_text: str, cfg: dict, emit_fn=None) -> tuple[str, str]:
    """Summarize a transcript via the provider chain. Returns (summary, provider_name)."""
    prompt_preamble = cfg.get('prompt', 'Summarize this transcript.')
    full_prompt = f"{prompt_preamble}\n\n{transcript_text}"
    return run_providers(full_prompt, cfg, emit_fn=emit_fn)
