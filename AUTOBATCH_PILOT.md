# AutoBatch pilot (isolated testing)

This branch is a copy of the deployed `Morgan2Fsub` code. The original `main` branch and legacy `/batch` command are unchanged.

## What the pilot does

- `/autobatch` (admin-only): list indexed series, preview seasons, and create one link per season.
- `/scanbatch FIRST_ID LAST_ID` (admin-only): inspect an explicit range of old DATABASE-channel message IDs (maximum 1,000 per call) without reposting media.
- New channel messages are indexed automatically when enabled.
- Recognized files are grouped by series, season, and episode number, regardless of unrelated posts between them.
- Duplicates and gaps within observed episode numbering are noted for review.
- Batch links resolve selected original Telegram message IDs, rather than an inclusive first-to-last range.
- Generated links keep their token when a season is regenerated.

## Safety / limitations

- **Off by default.** Set `AUTO_BATCH_ENABLED=True` only in ONE pilot Railway service. Do not enable it across all services using this repository.
- Keep the original code and backups. Do not merge the pilot PR into `main` or change other services until live testing passes.
- `/batch`, `/genlink`, and existing FSub behavior are still present.
- This is **filename/caption pattern recognition**, not an AI API integration. Recognized patterns: `S01E02`, `Season 1 Episode 2`, `1x02`.
- It does not infer completeness from an episode count. Episode gaps are detected between 1 and the highest observed episode; a short season with no gap may still be incomplete.
- Ambiguous or unlabeled files are skipped, not guessed. Mixed-source title aliases and multipart episodes need manual review/future improvement.
- `/scanbatch` depends on Telegram allowing this bot to retrieve older messages by ID in its configured DATABASE channel. There is **no guarantee** the bot can enumerate every old channel post; scan bounded ranges using known message IDs, and verify access on the pilot.
- No source file is moved, deleted, reposted, or re-ordered. MongoDB stores only references and index metadata.
- The pilot uses the existing MongoDB connection. Prefer a separated database name for testing to avoid writing into production data.
- Only admin users can create or scan batches. FSub membership checks still gate delivery.
- The bot's outgoing episode copies follow existing file-delivery rules and Telegram rate limits.
- Do not run two bot processes with the same Telegram bot token at the same time.

## Pilot plan

1. Run `python -m unittest discover -s tests -v` (no Telegram connection needed).
2. Choose a **single** Railway bot instance and isolate its branch to `feature/autobatch-pilot-20261123`.
3. Give that instance its own MongoDB database name (optional but recommended), and ensure its original DATABASE `CHANNEL_ID` is set.
4. Set `AUTO_BATCH_ENABLED=True` for the pilot only, then verify deployed status and logs.
5. Post a few labeled test episodes, interleave another show's file, run `/autobatch`, preview, create a link, and verify that it delivers only the selected files.
6. For older channel posts, run a small `/scanbatch` range and verify indexing before attempting larger ranges.
7. Confirm `/batch` and FSub still work.
8. Roll back the pilot service to its original branch if needed. The other services remain on `main`.

## Example output

```
BREAKING BAD

SEASON 1 - https://t.me/YourPilotBot?start=ab_<token1>
SEASON 2 - https://t.me/YourPilotBot?start=ab_<token2>
```

Real links are generated after a season is selected in the admin interface. No API key is required for this initial pilot.
