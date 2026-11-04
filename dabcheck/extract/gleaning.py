"""Gleaning (DocETL Sec. 3.2.1, Fig. 4): validator + refinement rounds on one map output."""
from __future__ import annotations
import json
from typing import Any, Dict, Optional, Sequence

from ..llm import BaseLLM
from .ops import render, Doc


def glean(llm: BaseLLM, doc: Doc, prompt: str, schema: Dict[str, str], *, validation_prompt: str,
          max_rounds: int = 2, model: Optional[str] = None, validator_model: Optional[str] = None,
          initial: Optional[Dict[str, Any]] = None, log: Optional[list] = None) -> Dict[str, Any]:
    """Eq. 7: Map -> (Map_validate -> Map_refine)^T.

    As in DocETL (operations/utils/api.py, gleaning), the validator receives the original prompt,
    the previous answer as an assistant turn and the validation instruction, and returns
    {should_refine, improvements}; the refinement call carries the whole chat history (original
    prompt, the model's previous response, the validator's feedback) and asks for an improved
    answer. Stops when the validator is satisfied or after max_rounds (DocETL default 2).
    """
    base = render(prompt, input=doc) + '\n\nReply with a JSON object with exactly this schema: ' + json.dumps(schema)
    messages = [{'role': 'user', 'content': base}]
    out = initial
    if out is None:
        res = llm.chat_json(messages, model=model, max_tokens=2000, tag='extract.glean.init')
        out = res if isinstance(res, dict) else {'value': res}
    for r in range(max_rounds):
        validator_messages = messages + [{'role': 'assistant', 'content': json.dumps(out, ensure_ascii=False)},
                                         {'role': 'user', 'content': ('Evaluate the previous response against this validation instruction: ' +
                                                                      render(validation_prompt, input=doc, output=out) +
                                                                      '\nReply with JSON: {"should_refine": true|false, "improvements": "specific, actionable feedback"}')}]
        v = None
        for _ in range(2):   # a malformed verdict is asked again, as DocETL's tool schema would enforce
            try: v = llm.chat_json(validator_messages, model=validator_model or model, max_tokens=600, tag='extract.glean.validate', retries=0)
            except ValueError: v = None
            if isinstance(v, dict) and 'should_refine' in v: break
            v = None
        if log is not None: log.append({'round': r, 'verdict': v})
        if not (v and v.get('should_refine')): break
        messages = messages + [{'role': 'assistant', 'content': json.dumps(out, ensure_ascii=False)},
                               {'role': 'user', 'content': 'Based on the validation feedback:\n```\n' + str(v.get('improvements', '')) +
                                                           '\n```\nPlease improve your previous response. Reply with the full corrected JSON object.'}]
        res = llm.chat_json(messages, model=model, max_tokens=2000, tag='extract.glean.refine')
        out = res if isinstance(res, dict) else {'value': res}
    return out
