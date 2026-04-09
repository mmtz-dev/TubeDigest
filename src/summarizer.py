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

    def get_setup_hint(self) -> str | None:
        """Return an actionable message when the provider is not available."""
        return None

    @abstractmethod
    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        """Generate a summary. Returns the summary text."""


class GeminiProvider(BaseProvider):
    name = 'gemini'

    def is_available(self) -> bool:
        return bool(os.environ.get('GEMINI_API_KEY'))

    def get_setup_hint(self) -> str | None:
        if not os.environ.get('GEMINI_API_KEY'):
            return 'GEMINI_API_KEY not set. Add it to your .env file.'
        return None

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

    def get_setup_hint(self) -> str | None:
        return 'Ollama is not running. Start it or install from https://ollama.com'

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


class ClaudeProxyProvider(BaseProvider):
    name = 'claude_proxy'

    def _proxy_url(self) -> str:
        return os.environ.get('CLAUDE_PROXY_URL', 'http://localhost:9100').rstrip('/')

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._proxy_url()}/health", method='GET')
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    data = json.loads(r.read())
                    return data.get('claude_available', False)
        except Exception:
            pass
        return False

    def get_setup_hint(self) -> str | None:
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"{self._proxy_url()}/health"), timeout=3
            )
        except Exception:
            return (
                f'Claude proxy not reachable at {self._proxy_url()}. '
                'Start the standalone claude-proxy Docker service.'
            )
        return 'Claude proxy is running but reports claude CLI unavailable.'

    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        full_prompt = f"{prompt}\n\n{transcript_text}"
        payload = json.dumps({
            'prompt': full_prompt,
            'model': cfg.get('claude_model', 'sonnet'),
            'timeout': 300,
        }).encode()
        req = urllib.request.Request(
            f"{self._proxy_url()}/generate",
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=330) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Claude proxy error {e.code}: {e.read().decode()}")
        if 'error' in data:
            raise RuntimeError(f"Claude proxy returned error: {data['error']}")
        result = data.get('result', '')
        return result if isinstance(result, str) else json.dumps(result)


class ClaudeCLIProvider(BaseProvider):
    name = 'claude_cli'

    def is_available(self) -> bool:
        return shutil.which('claude') is not None

    def get_setup_hint(self) -> str | None:
        if not shutil.which('claude'):
            return (
                'Claude Code is not installed. '
                'Install it from: https://docs.anthropic.com/en/docs/claude-code/getting-started'
            )
        return None

    def summarize(self, transcript_text: str, prompt: str, cfg: dict) -> str:
        result = subprocess.run(
            ['claude', '-p', prompt],
            input=transcript_text,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if any(kw in stderr.lower() for kw in ('auth', 'log in', 'login', 'sign in', 'api key', 'not authenticated')):
                raise RuntimeError(
                    'Claude Code is not logged in. '
                    'Run "claude" in your terminal to authenticate.'
                )
            raise RuntimeError(f"Claude CLI failed: {stderr}")
        return result.stdout.strip()


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    'claude_proxy': ClaudeProxyProvider,
    'gemini': GeminiProvider,
    'ollama': OllamaProvider,
    'claude_cli': ClaudeCLIProvider,
}


def summarize(transcript_text: str, cfg: dict, emit_fn=None) -> tuple[str, str]:
    """Try each configured provider in order, return (summary_text, provider_name).

    Falls back to the next provider on failure, matching the pattern in fetch_transcript_auto.
    """
    provider_names = cfg.get('providers', ['claude_cli', 'gemini', 'ollama'])
    prompt = cfg.get('prompt', 'Summarize this transcript.')
    errors = []

    for name in provider_names:
        cls = PROVIDER_REGISTRY.get(name)
        if not cls:
            log.warning("Unknown summarization provider: %s", name)
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
