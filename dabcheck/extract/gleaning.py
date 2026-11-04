"""Gleaning (DocETL Sec. 3.2.1, Fig. 4): validator + refinement rounds on one map output."""
from __future__ import annotations
import json
from typing import Any, Dict, Optional, Sequence

from ..llm import BaseLLM
from .ops import render, Doc


def glean(llm: BaseLLM, doc: Doc, prompt: str, schema: Dict[str, str], *, validation_prompt: str,
          max_rounds: int = 1, model: Optional[str] = None, validator_model: Optional[str] = None,
          initial: Optional[Dict[str, Any]] = None, log: Optional[list] = None) -> Dict[str, Any]:
    """Map_R (validator) checks the output against the original prompt and a task-specific
    validation prompt; Map_S refines it with the chat history retained. Stops when the
    validator is satisfied or after max_rounds."""
    base = render(prompt, input=doc) + '\n\nReply with a JSON object with exactly this schema: ' + json.dumps(schema)
    out = initial
    if out is None:
        res = llm.json(base, model=model, max_tokens=2000, tag='extract.glean.init')
        out = res if isinstance(res, dict) else {'value': res}
    history = ''
    for r in range(max_rounds):
        vuser = ('Original task given to another model:\n' + render(prompt, input=doc)[:6000] +
                 '\n\nIts output:\n' + json.dumps(out, ensure_ascii=False)[:4000] +
                 '\n\nValidation instruction: ' + render(validation_prompt, input=doc, output=out) +
                 '\n\nReply with JSON: {"needs_refinement": true|false, "feedback": "specific, actionable"}')
        v = llm.json(vuser, model=validator_model or model, max_tokens=600, tag='extract.glean.validate')
        if log is not None: log.append({'round': r, 'verdict': v})
        if not (isinstance(v, dict) and v.get('needs_refinement')): break
        history += ('\n\nPrevious answer:\n' + json.dumps(out, ensure_ascii=False)[:4000] +
                    '\nValidator feedback: ' + str(v.get('feedback', '')))
        res = llm.json(base + history + '\n\nImprove the answer using the feedback. Reply with the full corrected JSON.',
                       model=model, max_tokens=2000, tag='extract.glean.refine')
        out = res if isinstance(res, dict) else {'value': res}
    return out
