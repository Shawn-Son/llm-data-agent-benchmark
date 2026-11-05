"""Dataset-level preprocessing specs for the method conditions of the 104-question experiment.

Each spec is one preprocessing job that runs once per dataset before any agent session; its
outputs are staged into every task directory of that dataset. The specs describe *dataset*
structure that the database descriptions and hints already state (which columns hold noisy
join keys, which text columns hold numbers); they are never written for a particular question.

fdj     -> Identifier joins and identity    (FDJ, Zeighami et al., VLDB 2026)
docetl  -> Extraction and representation    (DocETL, Shankar et al., VLDB 2025)
The third condition, sqlverify (Text-to-SQL verification), needs no preprocessing.
"""
from __future__ import annotations

KEY = 'Two strings are noisy surface forms of an identifier (prefixes, suffixes, wrapper text, infix noise, case, separators, OCR-like substitutions, encodings).'

FDJ = [
    # cve: every table carries a noisy CVE key; vulns_db.cves is the registry the others are joined to.
    {'name': 'kev_to_vulns', 'dataset': 'cve', 'left': ('kev_db', 'kev_entries', 'cve_ref'), 'right': ('vulns_db', 'cves', 'cve_id'),
     'predicate': KEY + ' Join condition: LEFT and RIGHT encode the same CVE identifier (CVE-YYYY-NNNN).'},
    {'name': 'cvss_to_vulns', 'dataset': 'cve', 'left': ('vulns_db', 'cvss_metadata', 'cve_id'), 'right': ('vulns_db', 'cves', 'cve_id'),
     'predicate': KEY + ' Join condition: LEFT and RIGHT encode the same CVE identifier (CVE-YYYY-NNNN).'},
    {'name': 'cpe_to_vulns', 'dataset': 'cve', 'left': ('cpe_db', 'cpe_matches', 'cve_id'), 'right': ('vulns_db', 'cves', 'cve_id'),
     'predicate': KEY + ' Join condition: LEFT and RIGHT encode the same CVE identifier (CVE-YYYY-NNNN).'},
    {'name': 'descriptions_to_vulns', 'dataset': 'cve', 'left': ('descriptions_db', 'cve_documents', 'cve'), 'right': ('vulns_db', 'cves', 'cve_id'),
     'predicate': KEY + ' Join condition: LEFT and RIGHT encode the same CVE identifier (CVE-YYYY-NNNN).'},
    # usaspending: award ids and recipient UEIs differ per table (OCR, prefix, case, separators)
    {'name': 'amounts_to_contracts', 'dataset': 'usaspending', 'left': ('contracts_db', 'contract_amounts', 'award_id'),
     'right': ('contracts_db', 'contracts', 'award_id'),
     'predicate': KEY + ' Join condition: LEFT and RIGHT are the same canonical award id. A LEFT id ending in _OLD is a superseded entry and matches nothing.'},
    {'name': 'documents_to_contracts', 'dataset': 'usaspending', 'left': ('descriptions_db', 'contract_documents', 'award_id'),
     'right': ('contracts_db', 'contracts', 'award_id'),
     'predicate': KEY + ' Join condition: LEFT and RIGHT are the same canonical award id.'},
    {'name': 'recipients_to_contracts', 'dataset': 'usaspending', 'left': ('recipients_db', 'recipients', 'uei'),
     'right': ('contracts_db', 'contracts', 'recipient_uei'),
     'predicate': KEY + ' Join condition: LEFT and RIGHT are the same canonical recipient UEI.'},
    # music_brainz: duplicate track records (entity resolution, self-join over whole records)
    {'name': 'track_duplicates', 'dataset': 'music_brainz_20k', 'self': ('tracks_database', 'tracks', ['track_id', 'title', 'artist', 'album', 'year', 'length', 'language']),
     'id': 'track_id',
     'predicate': 'Join condition: LEFT and RIGHT are records of the same real-world recording (same song by the same artist), '
                  'possibly from different sources with different spellings, formats, abbreviations or missing fields.'},
    # civic: funding records name the same project in different ways
    {'name': 'funding_project_names', 'dataset': 'civic_unstructured', 'self': ('funding_database', 'Funding', ['project_name']),
     'id': 'project_name', 'distinct': True,
     'predicate': 'Join condition: LEFT and RIGHT are names of the same Malibu civic project (different wording, abbreviations or word order).'},
]

# DocETL extraction jobs: (alias, table, id columns, text column) and what to extract from the text.
NUM = r'(?P<value>\d{1,3}(?:,\d{3})+|\d+)'
DOCETL = [
    {'name': 'project_metrics', 'dataset': 'DEPS_DEV_V1', 'source': ('project_database', 'project_info', [], 'Project_Information'),
     'extract': [
         {'name': 'project_name', 'parse': 'text', 'description': 'GitHub repository path owner/repo',
          'patterns': [r'project\s+(?P<value>[\w.\-]+/[\w.\-]+)', r'(?P<value>[\w.\-]+/[\w.\-]+)']},
         {'name': 'stars', 'parse': 'int', 'description': 'GitHub stars count',
          'patterns': [NUM + r'\s+stars?\b', r'stars?\s+count\s+(?:of|is|:)?\s*' + NUM, r'starred\s+' + NUM + r'\s+times']},
         {'name': 'forks', 'parse': 'int', 'description': 'GitHub fork count',
          'patterns': [NUM + r'\s+forks?\b', r'forks?\s+count\s+(?:of|is|:)?\s*' + NUM, r'forked\s+' + NUM + r'\s+times']},
     ]},
    {'name': 'award_amounts', 'dataset': 'usaspending', 'source': ('contracts_db', 'contract_amounts', ['award_id'], 'amount_text'),
     'extract': [{'name': 'amount_usd', 'parse': 'amount', 'unit': 'USD', 'description': 'award amount in US dollars', 'patterns': []}]},
    {'name': 'recipient_totals', 'dataset': 'usaspending', 'source': ('recipients_db', 'recipients', ['uei'], 'total_amount_text'),
     'extract': [{'name': 'total_amount_usd', 'parse': 'amount', 'unit': 'USD', 'description': 'total amount in US dollars', 'patterns': []}]},
    {'name': 'agency_totals', 'dataset': 'usaspending', 'source': ('agencies_db', 'agencies', ['name'], 'total_amount_text'),
     'extract': [{'name': 'total_amount_usd', 'parse': 'amount', 'unit': 'USD', 'description': 'total awarded amount in US dollars', 'patterns': []}]},
    {'name': 'cvss_scores', 'dataset': 'cve', 'source': ('vulns_db', 'cvss_metadata', ['cve_id'], 'score_text'),
     'extract': [{'name': 'cvss_score', 'parse': 'number', 'description': 'CVSS v3 base score (0-10); the first numeric token',
                  'patterns': [r'(?P<value>\d+(?:\.\d+)?)']}]},
]

SPECS = {'fdj': FDJ, 'docetl': DOCETL}


def datasets(method: str):
    return sorted({s['dataset'] for s in SPECS.get(method, [])})
