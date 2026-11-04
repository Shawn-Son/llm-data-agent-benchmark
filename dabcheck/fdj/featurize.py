"""Featurizations and their LLM-driven generation (paper Sec. 5, Alg. 1-3).

A featurization is a triplet (d, X_L, X_R): two extraction functions and a distance
function. Extraction functions are either Python code (cheap, preferred) or an LLM
prompt applied per record. `get_candidate_featurizations` is the iterative generation
loop that uses cost-to-cover to pick the examples the LLM sees next.
"""
from __future__ import annotations
import json, math, re, textwrap, random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .distances import DISTANCES, DESCRIPTIONS
from ..llm import BaseLLM

Record = Any
Pair = Tuple[int, int]          # indices into L and R


class Extractor:
    """Callable record -> feature value with a per-record memo."""
    kind = 'code'

    def __init__(self, name: str = ''):
        self.name = name; self._memo: Dict[int, Any] = {}

    def extract(self, record: Record) -> Any: raise NotImplementedError

    def __call__(self, record: Record, key: Optional[int] = None) -> Any:
        k = id(record) if key is None else key
        if k not in self._memo:
            try: self._memo[k] = self.extract(record)
            except Exception: self._memo[k] = None   # an erroneous extractor yields "missing"
        return self._memo[k]


class CodeExtractor(Extractor):
    """Extractor from Python source defining `def extract(record): ...`.

    The source is usually LLM-generated (Alg. 2 line 15). It is executed with a small
    set of builtins and the `re`, `json`, `math`, `datetime` modules; anything else raises
    at construction time. This is not a security sandbox: only run code from an LLM you
    trust in a process you are willing to let it run in.
    """
    kind = 'code'
    SAFE_BUILTINS = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
                     for k in ['abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'float', 'int', 'isinstance', 'len',
                               'list', 'map', 'max', 'min', 'range', 'reversed', 'round', 'set', 'sorted', 'str',
                               'sum', 'tuple', 'zip', 'ValueError', 'TypeError', 'KeyError', 'Exception', 'None',
                               'True', 'False', 'filter', 'ord', 'chr', 'repr', 'divmod', 'pow', 'hash']}

    ALLOWED_MODULES = {'re', 'json', 'math', 'datetime', 'collections', 'itertools', 'string'}

    def __init__(self, source: str, name: str = ''):
        super().__init__(name); self.source = textwrap.dedent(source)
        import datetime, collections, itertools, string

        def guarded_import(mod, globals=None, locals=None, fromlist=(), level=0):
            if mod.split('.')[0] not in self.ALLOWED_MODULES:
                raise ValueError(f'import of {mod!r} is not allowed in a feature extractor')
            return __import__(mod, globals, locals, fromlist, level)
        builtins = dict(self.SAFE_BUILTINS); builtins['__import__'] = guarded_import
        env = {'__builtins__': builtins, 're': re, 'json': json, 'math': math, 'datetime': datetime,
               'collections': collections, 'itertools': itertools, 'string': string}
        exec(compile(self.source, f'<extractor {name}>', 'exec'), env)
        if 'extract' not in env or not callable(env['extract']): raise ValueError('source must define extract(record)')
        self._fn = env['extract']

    def extract(self, record): return self._fn(record)


class FunctionExtractor(Extractor):
    kind = 'code'

    def __init__(self, fn: Callable[[Record], Any], name: str = ''):
        super().__init__(name or getattr(fn, '__name__', 'fn')); self._fn = fn

    def extract(self, record): return self._fn(record)


class LLMExtractor(Extractor):
    """Extractor that asks the LLM per record (Alg. 2 line 13); replies are cached by the client."""
    kind = 'llm'

    def __init__(self, llm: BaseLLM, prompt: str, name: str = '', model: Optional[str] = None):
        super().__init__(name); self.llm = llm; self.prompt = prompt; self.model = model or getattr(llm, 'cheap_model', None)

    def extract(self, record):
        user = (self.prompt + '\n\nRecord:\n' + str(record)[:6000] +
                '\n\nReply with JSON: {"value": <extracted value or null>}')
        out = self.llm.json(user, model=self.model, max_tokens=300, tag='fdj.extract.' + self.name)
        return out.get('value') if isinstance(out, dict) else out


@dataclass
class Featurization:
    """phi = (d, X_L, X_R); phi(l, r) = d(X_L(l), X_R(r))."""
    name: str
    left: Extractor
    right: Extractor
    distance: str
    description: str = ''

    def __call__(self, l: Record, r: Record, lkey: Optional[int] = None, rkey: Optional[int] = None) -> float:
        return DISTANCES[self.distance](self.left(l, lkey), self.right(r, rkey))

    @property
    def cost_class(self) -> str:
        return 'llm' if 'llm' in (self.left.kind, self.right.kind) else 'code'


def distance_matrix(feats: Sequence[Featurization], L: Sequence[Record], R: Sequence[Record], pairs: Sequence[Pair]) -> List[List[float]]:
    """D[f][k] = feats[f](L[i], R[j]) for pairs[k] = (i, j)."""
    return [[f(L[i], R[j], i, j) for (i, j) in pairs] for f in feats]


# ---------------------------------------------------------------- cost to cover (Eq. 1, Alg. 3)

def cost_to_cover(D: Sequence[Sequence[float]], labels: Sequence[int]) -> List[int]:
    """For every positive pair, the minimum over featurizations of the number of negative
    pairs with distance <= the positive pair's distance (the false positives a single
    predicate must admit to classify that positive correctly)."""
    pos = [k for k, y in enumerate(labels) if y]; neg = [k for k, y in enumerate(labels) if not y]
    out = []
    for k in pos:
        best = len(neg) + 1 if D else len(neg) + 1
        for row in D:
            dk = row[k]
            if math.isinf(dk): c = len(neg) + 1   # unreachable with this featurization
            else: c = sum(1 for n in neg if row[n] <= dk)
            best = min(best, c)
        out.append(best)
    return out


def evaluate_and_pick_examples(D, labels, pairs, alpha: int = 10, beta: int = 20, rng: Optional[random.Random] = None):
    """Alg. 3: return [] when every positive is cheap to cover, else beta/2 hardest positives
    plus beta/2 negatives that beat at least one of them on some featurization."""
    rng = rng or random.Random(0)
    pos = [k for k, y in enumerate(labels) if y]; neg = [k for k, y in enumerate(labels) if not y]
    if not pos: return []
    costs = cost_to_cover(D, labels)
    if D and max(costs) < alpha: return []
    half = max(1, beta // 2)
    hard = [k for _, k in sorted(zip(costs, pos), key=lambda t: -t[0])[:half]]
    cand_neg = [n for n in neg if any(not math.isinf(row[k]) and row[n] <= row[k] for row in D for k in hard)] if D else list(neg)
    if len(cand_neg) > half: cand_neg = rng.sample(cand_neg, half)
    return [(pairs[k], 1) for k in hard] + [(pairs[n], 0) for n in cand_neg]


# ---------------------------------------------------------------- LLM pipeline (Alg. 2)

SYSTEM = ('You design cheap feature-based tests that approximate an expensive LLM join. '
          'Be concrete, handle missing values and inconsistent formats, and never repeat an existing feature.')


def _fmt_examples(L, R, examples, limit_chars=700):
    lines = []
    for (i, j), y in examples:
        lines.append(f'- label={"MATCH" if y else "NO MATCH"}\n  left: {str(L[i])[:limit_chars]}\n  right: {str(R[j])[:limit_chars]}')
    return '\n'.join(lines)


def walkthrough(llm: BaseLLM, L, R, examples, predicate: str, model: Optional[str] = None) -> str:
    """Reference walkthrough_examples: before proposing features the reasoning model discusses what
    the join condition means and walks through why each example does or does not satisfy it."""
    user = (f'Join condition between a LEFT record and a RIGHT record: "{predicate}"\n\nLabelled example pairs:\n'
            + _fmt_examples(L, R, examples) +
            '\n\nFirst, discuss what it means for the join condition to hold and the scenarios in which it can hold. '
            'Then walk through each example and show the logical steps that make the condition hold or fail.')
    return llm.complete(user, SYSTEM, model=model, max_tokens=1500, tag='fdj.walkthrough')


def generate_featurizations(llm: BaseLLM, L, R, examples, predicate: str, existing: Sequence[Featurization] = (),
                            max_new: int = 1, model: Optional[str] = None, discussion: Optional[str] = None) -> List[Featurization]:
    """get-featurization-from-examples (Alg. 2): descriptions -> per-side extractors -> distance.
    The reference generates one feature per call (max_rules = 1) and lists the previous rules' descriptions as
    "do not consider"."""
    if discussion is None: discussion = walkthrough(llm, L, R, examples, predicate, model)
    ex = _fmt_examples(L, R, examples)
    prior = '\n'.join(f'Rule {i + 1}: {f.description or f.name}' for i, f in enumerate(existing)) or '(none)'
    user = f"""Join condition between a LEFT record and a RIGHT record: "{predicate}"

Labelled example pairs:
{ex}

Discussion of the join condition and the examples:
{discussion[:4000]}

Do not consider the following rules, they are already considered:
{prior}

Design {max_new} new feature{'s' if max_new != 1 else ''} useful for deciding if the join condition is satisfied, focusing on
the MATCH examples that are hard to distinguish from the NO MATCH ones. A feature is an attribute value (a name, a
location, a date, an identifier, a number) or a specialised summary of one aspect of the record; do not mix several
attributes in one feature. Give a short snake_case name, a one-sentence description of how the feature helps decide
the join, and what to extract from each side.
Reply with JSON: [{{"name": ..., "description": ..., "left_feature": ..., "right_feature": ...}}]"""
    descs = llm.json(user, SYSTEM, model=model, max_tokens=1500, tag='fdj.descriptions')
    feats = []
    for d in (descs if isinstance(descs, list) else [])[:max_new]:
        if not isinstance(d, dict) or not d.get('name'): continue
        try:
            xl, spec_l = _make_extractor(llm, L, R, examples, predicate, d, 'left', model)
            xr, _ = _make_extractor(llm, L, R, examples, predicate, d, 'right', model, other_spec=spec_l)
            dist = _choose_distance(llm, d, xl, xr, L, R, examples, model)
            feats.append(Featurization(str(d['name']), xl, xr, dist, str(d.get('description', ''))))
        except Exception:  # a broken proposal is skipped; the loop may regenerate it
            continue
    return feats


def _make_extractor(llm, L, R, examples, predicate, desc, side, model, other_spec=None):
    """get-feature-extractors: decide code vs LLM, then obtain the code or the prompt. The second
    side is told the first side's operation so the two outputs use one format (reference
    feature_extract_prompt_get_extract_operation_col2). Returns (extractor, spec)."""
    recs = [str((L[i] if side == 'left' else R[j]))[:600] for (i, j), _ in examples[:6]]
    consistency = ''
    if other_spec:
        consistency = ('\nThe other side uses this operation; keep the output format consistent with it:\n' +
                       json.dumps({k: other_spec.get(k) for k in ('mode', 'prompt', 'output_format') if other_spec.get(k)})[:1500] + '\n')
    user = f"""Join condition: "{predicate}"
Feature "{desc['name']}": {desc.get('description','')}
For the {side.upper()} records, extract: {desc.get(side + '_feature','')}
{consistency}
Sample {side} records:
""" + '\n'.join('- ' + r for r in recs) + """

Decide whether this feature can be extracted reliably with Python code (regex / parsing) or needs an LLM.
If code: write a Python function `def extract(record):` that returns the feature value (a number, string,
date string, or list of strings) or None when absent. `record` is a dict or a string exactly like the samples.
Only `re`, `json`, `math`, `datetime`, `collections`, `itertools`, `string` may be imported. Make it robust to
missing fields and format variations. Prefer high recall: extracting extra information is better than missing some.
If LLM: write a precise extraction instruction the LLM will receive together with one record, including a
standardised output format (do not rely on the input's own formatting).
Reply with JSON: {"mode": "code" | "llm", "code": "...", "prompt": "...", "output_format": "<python type hint>"}"""
    spec = llm.json(user, SYSTEM, model=model, max_tokens=1500, tag=f'fdj.extractor.{side}')
    if not isinstance(spec, dict): spec = {}
    name = f"{desc['name']}.{side}"
    if spec.get('mode') == 'code' and spec.get('code'):
        ex = CodeExtractor(spec['code'], name)
        # smoke-test on the samples; fall back to an LLM extractor when the code never produces a value
        vals = [ex(r, k) for k, r in enumerate(L if side == 'left' else R) if k < 20]
        if any(v not in (None, '', [], {}) for v in vals): return ex, spec
    prompt = spec.get('prompt') or f"Extract {desc.get(side + '_feature','')} from the record."
    if spec.get('output_format'): prompt += f"\nOutput format: {spec['output_format']}"
    return LLMExtractor(llm, prompt, name), spec


def _choose_distance(llm, desc, xl, xr, L, R, examples, model) -> str:
    shown = []
    for (i, j), y in examples[:8]:
        shown.append(f'- label={"MATCH" if y else "NO MATCH"}: left={xl(L[i], i)!r} right={xr(R[j], j)!r}')
    options = '\n'.join(f'- {k}: {v}' for k, v in DESCRIPTIONS.items())
    user = f"""Feature "{desc['name']}": {desc.get('description','')}
Extracted values on labelled pairs:
""" + '\n'.join(shown) + f"""

Choose the distance function that best separates MATCH from NO MATCH on this feature:
{options}
Reply with JSON: {{"distance": "<name>"}}"""
    out = llm.json(user, SYSTEM, model=model, max_tokens=200, tag='fdj.distance')
    name = out.get('distance') if isinstance(out, dict) else None
    return name if name in DISTANCES else 'char_edit'


def get_candidate_featurizations(llm: BaseLLM, L, R, pairs: Sequence[Pair], labels: Sequence[int], predicate: str,
                                 *, seed: Sequence[Featurization] = (), max_iter: int = 4, alpha: int = 10,
                                 beta: int = 10, n_examples: int = 5, model: Optional[str] = None,
                                 rng: Optional[random.Random] = None, log: Optional[list] = None) -> List[Featurization]:
    """Alg. 1: an initial generation from `n_examples` random positives and negatives, then up to
    max_iter rounds of (evaluate with cost-to-cover, pick hard examples, generate one more feature).
    The reference stops when the costliest positive is below alpha (max_cost = 10)."""
    rng = rng or random.Random(0)
    feats = list(seed)
    pos = [k for k, y in enumerate(labels) if y]; neg = [k for k, y in enumerate(labels) if not y]
    examples = [(pairs[k], 1) for k in rng.sample(pos, min(n_examples, len(pos)))] + \
               [(pairs[k], 0) for k in rng.sample(neg, min(n_examples, len(neg)))]
    discussion = walkthrough(llm, L, R, examples, predicate, model)
    feats.extend(generate_featurizations(llm, L, R, examples, predicate, feats, model=model, discussion=discussion))
    for it in range(max_iter):
        D = distance_matrix(feats, L, R, pairs)
        c = cost_to_cover(D, labels) if feats and pos else []
        examples = evaluate_and_pick_examples(D, labels, pairs, alpha=alpha, beta=beta, rng=rng)
        if log is not None:
            log.append({'iteration': it, 'n_features': len(feats), 'features': [f.name for f in feats], 'max_cost_to_cover': max(c) if c else None})
        if not examples: break
        new = generate_featurizations(llm, L, R, examples, predicate, feats, model=model, discussion=discussion)
        if not new: break
        feats.extend(new)
    return feats
