# Z1_Guide_EDITED.docx: sector/instrument code fix

## The problem

Chapter 3 (§3.1, paragraph beginning "A note on where these numbers come from") correctly says the nine digits after the prefix split as **2-digit sector / 4-digit instrument / 3-digit detail**, and warns that the alternative **3 / 2 / 4** split is wrong. The rest of the book still uses the 3/2/4 split. The warning is right; the other parts were not updated.

Evidence, from the current Fed release (`z1_master.db`, 8,232 parsed series). It is the Guide's own test: does a candidate code map to one stable description?

| Split | "Sectors" | "Instruments" | Verdict |
|---|---|---|---|
| **2 / 4 / 3** (Chapter 3) | **58** | **179** | matches Chapter 3's 55 / 178 (the data has grown since the book's 7,703-series build) |
| 3 / 2 / 4 (Appendices, Ch. 21) | 254 | 33 | the fabricated "247 / 33" Chapter 3 already warns about |

Cross-check: `FL153166000` is `FL | 15 | 3166 | 000`. The 3/2/4 split reads the sector as `153`, which is really sector `15` plus the first digit of the instrument. Instruments starting with `3` or `4` carry the side in their second digit (`30xx` asset, `31xx` liability), so `153` / `154` mean "households, assets side / liabilities side", not sectors. Appendix B's own tables can't tell you that, because they list `153` and `154` as separate "sectors".

## Edits, in document order

Paragraph numbers are 0-based paragraph indexes of `document.xml`; searching for the quoted text is easier.

### E1. Edition note, front matter (para 2)
Append: "Chapter 3, Chapter 21 and Appendices A–C were repaired to the 2-digit sector / 4-digit instrument / 3-digit detail split in the same pass."

### E2. §3.3 anatomy tables (paras 233–262)
- "SECTOR (3 digits)" → **"SECTOR (2 digits)"**
- "INSTRUMENT (2 digits)" (para 234) → **"INSTRUMENT (4 digits)"**; the DETAIL line becomes **"DETAIL (3 digits)"**.
- Example rows:

| Series | Prefix | Sector | Instrument | Detail | Freq |
|---|---|---|---|---|---|
| FL153166000.Q | FL | **15** | **3166** | **000** | Q |
| FL764194005.Q | FL | **76** | **4194** | **005** | Q |
| FL313161105.Q | FL | **31** | **3161** | **105** | Q |

(The existing "Real description" cells stay as they are.)

### E3. §3.3 "Notice something worth flagging" (para 266), replace the whole paragraph
> Notice how much the instrument code does. FL153166000.Q and FL313161105.Q are both liabilities (each instrument code has a 1 in the second position), and both are credit instruments, but their instrument codes differ: 3166 is consumer credit and 3161 is marketable Treasury securities. The sector code tells you who owes it (15, households; 31, federal government); the instrument code tells you what is owed. Even so, the description, not a mental reconstruction from the digits alone, is always the authoritative statement of what a series measures. Decoding the digits tells you where to look; it doesn't replace reading what's there.

Why: the old text claims the two series "share the same instrument code, 16" and then explains the clash with "closely held corporate equities". That is an artifact of the wrong split, not a property of the data.

### E4. Chapter 21 decode paragraph (para 1080)
Replace "FL153166000.Q is prefix (FL, a stock/level), sector (153, households), instrument (16, consumer-credit-adjacent loans), detail (6000), and frequency (Q). Decoding this once … turns an opaque string into four queryable columns." with:
> FL153166000.Q is prefix (FL, a stock/level), sector (15, households), instrument (3166, consumer credit; the 1 in second position marks a liability), detail (000), and frequency (Q). Decoding this once, at parse time, with a single regular expression, turns an opaque string into five queryable columns.

### E5. Every regex (paras 282, 1110, 1117, and the `parse_code` row in the function index)
Replace
```python
re.compile(r"([A-Z]+)(\d{3})(\d{2})(\d{4})\.([AQMD])")      # para 282
re.match(r'([A-Z]+)(\d{3})(\d{2})(\d{4})\.([AQ])', code)     # paras 1110, 1117
```
with
```python
re.compile(r"([A-Z]{2})(\d{2})(\d{4})(\d{3})\.([AQ])")
```
(group order stays prefix, sector, instrument, detail, freq; para 282's `[AQMD]` should stay `[AQMD]` if the book supports M/D, else drop to `[AQ]`).
Also para 1110's docstring example ("894: sector (All sectors) - 11: instrument class (interbank) - 0005") → `FL894090005`: prefix FL, sector **89** (All sectors), instrument **4090** (total financial assets), detail **005**.

### E6. Chapter 21 queries and exercises
- Para 1122: `sector_code LIKE '11%'` → `sector_code = '11'`.
- The `v_household_levels` view: `WHERE s.sector_code LIKE '15%'` → `WHERE s.sector_code = '15'` (the `LIKE` still works with 2-digit codes but reads as if the code had a third digit).
- Para 1626: "another 76x or 70x sector code" → "another sector such as 70 or 76".

### E7. Appendix A caution (para 2300), replace
> This book's parse_code() regex (Chapter 21) captures the two digits immediately following the prefix as sector_code, the next four as instrument_code, and the final three as detail_code, for every series uniformly. That parsing is reliable for the standard FA/FL/FU-prefixed sector-and-instrument series this book relies on throughout, but some specialized code families (Integrated Macroeconomic Accounts income-statement lines, the Flow of Funds Matrix) use the same digit positions for different purposes. Appendix B and C below present the parsed values honestly, as what the single shared regex extracts, not as a claim that every entry is a clean SNA sector or instrument code.

### E8. Appendix B (paras 2302–2367): regenerate
Heading line: "58 unique 2-digit sector codes exist in this book's database, parsed by the method described in Appendix A. The 20 most frequently represented, by real series count:" followed by the table below. Last paragraph (para 2367) becomes: "The sector codes this book's chapters actually built analysis around: 15 (households, Chapters 5, 18, 24, 27, 28), 10 (nonfinancial corporate, Chapters 6, 25, 32), 76 / 79 (depository institutions / domestic financial sectors, Chapters 8, 25, 26, 30, 32), 31 (federal government, Chapters 7, 27–30)."

(Check the chapter lists against the text before committing to them; they were carried over from the old paragraph.)

| Code | Series | Sector |
|---|---|---|
| 26 | 583 | Rest of the world |
| 31 | 486 | Federal government |
| 10 | 485 | Nonfinancial corporate business |
| 15 | 478 | Households and nonprofit organizations |
| 79 | 459 | Domestic financial sectors |
| 54 | 371 | Life insurance companies |
| 21 | 355 | State and local governments |
| 11 | 341 | Nonfinancial noncorporate business |
| 89 | 300 | All sectors |
| 76 | 288 | U.S.-chartered depository institutions |
| 71 | 264 | Central bank |
| 70 | 225 | Private depository institutions |
| 38 | 205 | Domestic nonfinancial sectors |
| 57 | 202 | Private pension funds |
| 59 | 186 | Pension funds |
| 66 | 171 | Security brokers and dealers |
| 75 | 170 | Foreign banking offices in the U.S. |
| 14 | 168 | Nonfinancial business |
| 50 | 157 | Other financial business |
| 40 | 155 | Government-sponsored enterprises |

### E9. Appendix C (paras 2369–~2440): regenerate
Heading: "179 unique 4-digit instrument codes exist in this book's database. By real series count:" then:

| Code | Series | Most common description |
|---|---|---|
| 3064 | 434 | corporate equities; asset |
| 3065 | 397 | total mortgages; asset |
| 3061 | 372 | agency- and GSE-backed securities; asset |
| 3069 | 298 | other loans and advances; asset |
| 4090 | 246 | total financial assets |
| 3169 | 229 | other loans and advances; liability |
| 3063 | 215 | corporate and foreign bonds; asset |
| 4022 | 196 | debt securities; asset |
| 3092 | 177 | equity in FHLB; asset |
| 3164 | 166 | corporate equities; liability |
| 5013 | 156 | gross fixed investment, nonresidential structures, equipment, and intellectual property products |
| 4190 | 147 | total liabilities |
| 3192 | 146 | foreign direct investment in U.S.: intercompany debt; liability (market value) |
| 3062 | 134 | municipal securities; asset |
| 3020 | 131 | checkable deposits and currency; asset |
| 4035 | 127 | total loans; asset |
| 3030 | 123 | total time and savings deposits; asset |
| 3090 | 110 | total miscellaneous assets |
| 3034 | 108 | money market fund shares; asset |
| 4194 | 108 | total liabilities and equity |

Both tables come from `python guide_appendix.py` against the current release. Regenerate them if the book is rebuilt on a newer release.

## Not errors, but be aware

- **Vintage.** The book's 7,703 series / 55 sectors / 178 instruments describe an older release. The current data has 8,234 series (8,232 parse), 58 sectors and 179 instruments. Either date the counts ("as of the release this book was built on") or update them.
- **The API uses a finer instrument.** `series.instrument` in this repo's database is 5 digits and `suffix` is 2 (`FL153166000` → instrument `31660`, suffix `00`). The Guide's 4-digit instrument is the first four digits of the API's `instrument`; sectors are identical in both. Say so wherever the book shows API output.
- **Chapter 21's "confirmed identical everywhere it appears".** `ingest.py` now enforces that claim: it aborts if any two CSV files disagree on a cell.
