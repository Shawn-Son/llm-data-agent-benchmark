"""dabcheck: verification modules for data agents, built from three VLDB papers.

- dabcheck.fdj       Featurized-Decomposition Join (Zeighami, Shankar, Parameswaran; VLDB 2026)
                     for identifier joins over noisy keys.
- dabcheck.extract   DocETL-style extraction pipelines (Shankar et al.; VLDB 2025):
                     code-first extraction, parse-coverage reports, LLM map with
                     gleaning, resolve, reduce with folding.
- dabcheck.sqlverify Text-to-SQL verification (Alrashed, Sukoon, Karger, Noy; VLDB 2026):
                     round-trip critique, synthetic execution consistency, direct
                     critique, plus a cohort/temporal intent check for data agents.

Every LLM call goes through dabcheck.llm.LLM; tests use dabcheck.llm.MockLLM.
"""
from .llm import LLM, MockLLM, get_llm

__all__ = ['LLM', 'MockLLM', 'get_llm']
__version__ = '0.1.0'
