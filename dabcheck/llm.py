"""Thin LLM client used by every dabcheck module.

Design goals: one place for model names, caching, cost accounting and robust JSON
parsing; a MockLLM with the same interface so every algorithm is testable offline.
"""
from __future__ import annotations
import hashlib, json, os, re, threading, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_MODEL = os.environ.get('DABCHECK_MODEL', 'claude-sonnet-5-5')   # generation, critique
CHEAP_MODEL = os.environ.get('DABCHECK_CHEAP_MODEL', 'claude-haiku-5-5')  # per-row extraction, labelling
KEY_FILE = Path(os.environ.get('DABCHECK_KEY_FILE', '~/.config/dab/anthropic_key')).expanduser()
CACHE_DIR = Path(os.environ.get('DABCHECK_CACHE', '~/.cache/dabcheck')).expanduser()

# USD per million tokens (input, output); used only for the running estimate in LLM.usage.
PRICES = {'claude-haiku-5-5': (0.10, 0.50), 'claude-sonnet-5-5': (2.0, 10.0), 'claude-opus-5-5': (4.0, 20.0)}


def load_api_key() -> Optional[str]:
    key = os.environ.get('ANTHROPIC_API_KEY')
    if key: return key.strip()
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
        if key: return key
    return None


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a model reply (handles ``` fences and prose)."""
    text = text.strip()
    fence = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fence: text = fence.group(1).strip()
    try: return json.loads(text)
    except ValueError: pass
    for opener, closer in (('{', '}'), ('[', ']')):
        start = text.find(opener)
        while start != -1:
            depth = 0; in_str = False; esc = False
            for i in range(start, len(text)):
                c = text[i]
                if in_str:
                    if esc: esc = False
                    elif c == '\\': esc = True
                    elif c == '"': in_str = False
                    continue
                if c == '"': in_str = True
                elif c == opener: depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        try: return json.loads(text[start:i + 1])
                        except ValueError: break
            start = text.find(opener, start + 1)
    raise ValueError('no JSON value found in reply: ' + text[:200])


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cached_calls: int = 0
    cost_usd: float = 0.0

    def add(self, model: str, inp: int, out: int, cache_read: int = 0):
        self.calls += 1; self.input_tokens += inp; self.output_tokens += out; self.cache_read_tokens += cache_read
        pi, po = PRICES.get(model, (2.0, 10.0))
        self.cost_usd += ((inp - cache_read) * pi + cache_read * pi * 0.1 + out * po) / 1e6

    def as_dict(self): return dict(self.__dict__)


TRUNCATED = '\n[TRUNCATED: max_tokens reached]'
MAX_TOKENS_CAP = 16000


class BaseLLM:
    """Interface shared by LLM and MockLLM."""
    usage: Usage

    def complete(self, user: str, system: str = '', *, model: Optional[str] = None,
                 max_tokens: int = 4096, effort: str = 'low', tag: str = '') -> str:
        raise NotImplementedError

    def chat(self, messages: list, system: str = '', *, model: Optional[str] = None, max_tokens: int = 4096,
             effort: str = 'low', tag: str = '') -> str:
        """Multi-turn completion over [{'role': 'user'|'assistant', 'content': str}, ...]. The default
        implementation flattens the history into one user turn; LLM overrides it with real turns."""
        flat = '\n\n'.join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages)
        return self.complete(flat, system, model=model, max_tokens=max_tokens, effort=effort, tag=tag)

    def json(self, user: str, system: str = '', *, retries: int = 1, **kw) -> Any:
        """complete() and parse JSON. A reply cut off by max_tokens is retried with twice the room
        (thinking tokens count against max_tokens); an unparseable reply is asked for once more."""
        reply = self.complete(user, system, **kw)
        if reply.endswith(TRUNCATED) and kw.get('max_tokens', 4096) < MAX_TOKENS_CAP:
            kw = dict(kw, max_tokens=min(MAX_TOKENS_CAP, 2 * kw.get('max_tokens', 4096)))
            return self.json(user, system, retries=retries, **kw)
        try: return extract_json(reply)
        except ValueError as e:
            if retries <= 0: raise
            fix = user + '\n\nYour previous reply could not be parsed as JSON (' + str(e)[:120] + \
                  '). Reply with only the JSON value.'
            return self.json(fix, system, retries=retries - 1, **kw)

    def chat_json(self, messages: list, system: str = '', *, retries: int = 1, **kw) -> Any:
        reply = self.chat(messages, system, **kw)
        if reply.endswith(TRUNCATED) and kw.get('max_tokens', 4096) < MAX_TOKENS_CAP:
            kw = dict(kw, max_tokens=min(MAX_TOKENS_CAP, 2 * kw.get('max_tokens', 4096)))
            return self.chat_json(messages, system, retries=retries, **kw)
        try: return extract_json(reply)
        except ValueError as e:
            if retries <= 0: raise
            return self.chat_json(messages + [{'role': 'assistant', 'content': reply},
                                              {'role': 'user', 'content': 'That could not be parsed as JSON (' + str(e)[:120] + '). Reply with only the JSON value.'}],
                                  system, retries=retries - 1, **kw)


class LLM(BaseLLM):
    """Anthropic Messages API client with a disk cache (same prompt -> same answer, no spend)."""

    def __init__(self, model: str = DEFAULT_MODEL, cheap_model: str = CHEAP_MODEL, api_key: Optional[str] = None,
                 cache: bool = True, cache_dir: Path = CACHE_DIR, max_retries: int = 3):
        self.model = model; self.cheap_model = cheap_model
        self.api_key = api_key or load_api_key()
        if not self.api_key:
            raise RuntimeError(f'No Anthropic API key: set ANTHROPIC_API_KEY or write it to {KEY_FILE}')
        import anthropic
        self._client = anthropic.Anthropic(api_key=self.api_key, max_retries=max_retries)
        self.cache = cache; self.cache_dir = Path(cache_dir); self.usage = Usage()
        self._lock = threading.Lock()
        if cache: self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, model, system, user, max_tokens, effort):
        h = hashlib.sha256(json.dumps([model, system, user, max_tokens, effort]).encode()).hexdigest()
        return self.cache_dir / (h[:2]) / (h + '.json')

    def complete(self, user, system='', *, model=None, max_tokens=4096, effort='low', tag=''):
        return self.chat([{'role': 'user', 'content': user}], system, model=model, max_tokens=max_tokens, effort=effort, tag=tag)

    def chat(self, messages, system='', *, model=None, max_tokens=4096, effort='low', tag=''):
        model = model or self.model
        key = json.dumps(messages, ensure_ascii=False)
        path = self._cache_path(model, system, key, max_tokens, effort) if self.cache else None
        if path and path.exists():
            with self._lock: self.usage.cached_calls += 1
            return json.loads(path.read_text())['text']
        kwargs = dict(model=model, max_tokens=max_tokens, messages=[{'role': m['role'], 'content': m['content']} for m in messages],
                      output_config={'effort': effort})
        if system: kwargs['system'] = system
        resp = self._client.messages.create(**kwargs)
        if resp.stop_reason == 'refusal':
            raise RuntimeError(f'model refused ({tag}): {getattr(resp, "stop_details", None)}')
        text = ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text')
        truncated = resp.stop_reason == 'max_tokens'
        if truncated: text += TRUNCATED
        u = resp.usage
        with self._lock:
            self.usage.add(model, (u.input_tokens or 0) + (getattr(u, 'cache_read_input_tokens', 0) or 0)
                           + (getattr(u, 'cache_creation_input_tokens', 0) or 0), u.output_tokens or 0,
                           getattr(u, 'cache_read_input_tokens', 0) or 0)
        if path and not truncated:   # a truncated reply is never cached: the caller retries with more room
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'model': model, 'tag': tag, 'text': text, 'time': time.time()}))
        return text


class MockLLM(BaseLLM):
    """Deterministic stand-in for tests and dry runs.

    `handler(user, system, tag) -> str` decides the reply; `responses` is an optional
    list consumed in order. Every call is recorded in `log`.
    """

    def __init__(self, handler: Optional[Callable[[str, str, str], str]] = None, responses: Optional[list] = None):
        self.handler = handler; self.responses = list(responses or []); self.log = []
        self.usage = Usage(); self.model = 'mock'; self.cheap_model = 'mock'

    def complete(self, user, system='', *, model=None, max_tokens=4096, effort='low', tag=''):
        self.log.append({'user': user, 'system': system, 'tag': tag, 'model': model})
        self.usage.calls += 1
        if self.responses: return self.responses.pop(0)
        if self.handler: return self.handler(user, system, tag)
        raise RuntimeError(f'MockLLM has no response for tag={tag!r}')

    def chat(self, messages, system='', *, model=None, max_tokens=4096, effort='low', tag=''):
        """Logs the full message list; the handler receives the last user turn (and `messages`
        through the log) so tests can assert on the retained history."""
        self.log.append({'messages': list(messages), 'user': messages[-1]['content'], 'system': system, 'tag': tag, 'model': model})
        self.usage.calls += 1
        if self.responses: return self.responses.pop(0)
        if self.handler: return self.handler(messages[-1]['content'], system, tag)
        raise RuntimeError(f'MockLLM has no response for tag={tag!r}')


_default: Optional[BaseLLM] = None


def get_llm(required: bool = True) -> Optional[BaseLLM]:
    """Process-wide LLM; None (or an error) when no API key is configured."""
    global _default
    if _default is None:
        try: _default = LLM()
        except RuntimeError:
            if required: raise
            return None
    return _default
