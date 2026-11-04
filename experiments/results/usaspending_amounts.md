# usaspending amount_text extraction (offline)

rows: 10266; exact-format rows parsed by code: 681 (6.6%); numeric rows > $1M: 98; rows with _OLD suffix: 0

Warnings:
- award_amount: parse coverage 6.6% < 95% (9585 of 10266 rows unparsed)
- award_amount: final coverage 6.6% after code+LLM; the answer may rest on a subset of rows

Unparsed samples:
- This Department of Defense contract with Utah State University's Space Dynamics Laboratory represents a significant portion that aligns with eight-figure invest
- The Department of Defense's award to EBL Engineers, LLC, represents a mid-tier commitment typical for minor engineering consultancies, hovering in the six-figur
- For the Department of Veterans Affairs, VALHALLA ENGINEERING GROUP, LLC's contract represents a strategic outlay characteristic of targeted six-figure commitmen
- In the realm of aircraft manufacturing, this Department of Defense contract entrusted to Lockheed Martin Corp signifies a ten-figure commitment, underscoring th
- The Department of Defense's partnership with The Boeing Company in aircraft manufacturing reflects a scale consistent with substantial, nation-shaping investmen

award_id join audit (contracts vs contract_amounts):
best rule raw: raw=9921, strip_hash_case=9921, numeric_id=6730, ocr_fold_digits=9242
