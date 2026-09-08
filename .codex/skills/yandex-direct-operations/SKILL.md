---
name: yandex-direct-operations
description: Safely creates, copies, edits, audits, moderates, and launches Yandex Direct Search and RSYA campaigns with mandatory campaign-group-ad verification. Use for any work in Yandex Direct, including settings, targeting, corrections, minus phrases, placements, ads, Metrika goals, attribution, moderation, or readiness-to-launch checks.
---

# Yandex Direct Operations

## Purpose

Prevent partially configured campaigns. Treat a Direct campaign as three separate configuration levels: campaign, group, and ad. Never infer that copying one level copied the other two.

## Operating rules

1. Use the Direct API first for inventory, bulk reads, supported edits, and post-edit verification. Use the UI for fields the API omits, renders ambiguously, or requires visually checking.
2. Preserve the current campaign status during preparation. A save must not become a launch.
3. Never create or duplicate a campaign, send it to moderation when that may start delivery, resume it, or launch it unless Sergey explicitly authorized that exact action.
4. After every mutation, re-read the affected object. A successful request or visible toast is not sufficient verification.
5. Do not say "готово к запуску" until every applicable item in the final acceptance matrix is `PASS`. Report blockers instead of silently using defaults.
6. Record campaign, group, and ad IDs in the task checkpoint so a later chat can reproduce the audit.

Choose the verification depth before acting:

- For a narrow read or explicitly scoped edit, inspect the affected level plus its status and dependencies, make the change, and re-read it. Do not run the full launch audit.
- For creation, duplication, broad reconfiguration, moderation, launch, or any claim that a campaign is ready, run every applicable phase below and produce the final acceptance matrix.

## Phase 1: recover the brief

Before broad preparation, extract decisions already made in the current task and its checkpoint. Do not ask again when the answer is already recorded. Resolve and record:

- campaign purpose and type: Search or RSYA;
- account balance, usable credit/overdraft, and any payment blocker;
- landing URL and attribution path;
- budget, strategy, payment model, and any bid or CPA limit;
- geography, schedule, age, gender, and device corrections;
- Metrika counter, optimization goal, and goal value;
- if the strategy optimizes conversions, a recent Direct report row proving that the
  selected goal actually receives attributed conversions;
- UTM template and preservation of `yclid`;
- targeting mechanism for every group;
- campaign and group minus phrases;
- excluded RSYA placements;
- site monitoring, automatic recommendations, and ad personalization;
- ad texts, images or video, extensions, and naming;
- current authorization boundary: prepare, create, moderate, or launch.

If using a reference campaign, first read all three levels of the reference. Create or duplicate only after authorization. Then read all three levels of the resulting target and list intentional differences before further edits.

## Phase 2: configure the campaign level

Verify each item independently:

- name and campaign ID;
- delivery surfaces match the intended type;
- strategy, payment model, weekly budget, limits, and start/end dates;
- Metrika counter and optimization goal are present and resolvable;
- geography, timezone, and schedule;
- all agreed age, gender, and device corrections, with no overlapping-rule errors;
- UTM parameters and landing domain;
- campaign minus phrases;
- site monitoring;
- automatic recommendations and Yandex Neuro Ads state;
- excluded placements for RSYA;
- campaign remains stopped while preparing.

## Phase 3: configure every group

Every group must have at least one deliberate delivery condition.

### Search

Verify:

- keyword phrases exist and belong to the group intent;
- autotargeting categories are explicitly configured, not left as an accidental default;
- group minus phrases do not conflict with useful intent;
- geography inheritance or override is intentional;
- at least one valid ad is attached.

### RSYA

Verify:

- RSYA delivery is enabled and Search delivery is not;
- at least one targeting source is active: autotargeting, thematic phrases, interests, or retargeting segments;
- if the plan is algorithmic RSYA without thematic phrases, confirm `autotargeting = ON` and document that empty thematic phrases are intentional;
- offer retargeting is OFF unless the campaign explicitly promotes a product feed;
- group minus phrases, interests, and segments are deliberate rather than inherited by accident;
- at least one valid ad is attached.

An RSYA group with no active targeting source is a hard blocker.

## Phase 4: configure and compare ads

For every ad, verify:

- ad ID and status;
- landing URL and attribution parameters;
- headline, additional headline, body, and character limits;
- image/video actually attached and visible in preview;
- sitelinks, callouts, and other extensions;
- moderation state and rejection reasons;
- experiment isolation: only the intended variable differs between variants.

For an image test, keep headline, body, extensions, landing URL, targeting, and budget identical. Do not replace an image inside the same ad when clean historical comparison is required; use separate ad IDs.

## Phase 5: double verification

Run two passes before handoff:

1. API pass: re-read campaign, groups, ads, keywords/autotargeting, corrections, minus phrases, and statuses wherever supported.
2. UI pass: open the exact campaign and inspect all collapsed advanced settings, every group, and every ad preview. Confirm images visually.

Then produce an acceptance matrix with `PASS`, `FAIL`, or `N/A` for:

- campaign type and surfaces;
- strategy, payment model, budget, and limits;
- account funding or usable credit;
- counter and goal;
- optimization signal reaches Direct for conversion-based strategies;
- geography, timezone, schedule, and start/end dates;
- corrections;
- UTM and attribution;
- campaign negatives;
- site monitoring;
- excluded placements;
- automatic recommendations and ad personalization;
- group targeting source;
- group negatives/segments;
- ad count, texts, extensions, links, and media;
- moderation state;
- campaign and group stopped/running status.

If any item is `FAIL` or unknown, the campaign is not ready.

## Phase 6: experiment protocol

Before preparing an experiment, read
[`YANDEX_DIRECT_CREATIVE_TESTING.md`](../../../docs/knowledge-base/YANDEX_DIRECT_CREATIVE_TESTING.md).
It owns the research model, historical benchmarks, evidence thresholds, owner preferences,
and decision log. Record the hypothesis, primary metric, guardrails, and stopping rule before
launch; do not redefine the test after seeing early results.

- Use `bot_start` as the primary early decision metric. Use landing-to-bot conversion, CTR,
  and CPC to diagnose the funnel. Treat payments as delayed confirmation because the sales
  cycle is 30+ days.
- Distinguish optimization from causal learning. Several ads in one group let Direct allocate
  traffic toward predicted performance, but do not provide equal exposure or isolate causes.
- With a limited budget, use a controlled tournament: pre-moderate separate immutable ad IDs,
  keep the campaign and strategy active, and alternate one control and one challenger in complete
  time blocks defined by the canonical document. This guarantees spend to both variants but is
  still sequential screening, not causal proof. Confirm only the best two through Direct's A/B
  experiment with comparable campaigns and one changed variable.
- For an isolated test, change only one layer: creative (image plus its native meme text),
  headline, landing, or supporting description. Use two variants at a time. Keep targeting,
  strategy, budget allocation, extensions, and every other layer fixed.
- Derive the evidence threshold from the baseline and smallest useful improvement. Use the
  canonical document's operational thresholds only as economy-oriented gates, not universal
  statistical proof. A large difference can support an early provisional decision; a small
  difference needs substantially more data.
- Record both a maximum experiment spend and a calendar end date. Define stop-loss rules for
  zero conversions and for nonzero conversions above the affordable CPA. Reaching either cap
  forces stop, extension approval, or a provisional no-decision result.
- Do not start a CPA Start experiment merely because the goal ID is configured. A recent Direct
  report must contain attributed `bot_start` conversions with the expected ad IDs. Internal Start
  rows with zero Direct conversions are a hard blocker until delivery is repaired or the owner
  explicitly chooses a CTR-only strategy and accepts its learning reset.
- Record every material edit with timestamp, `test_id`, object IDs, old value, new value, reason,
  and test version. Never overwrite a historical creative inside an existing ad when comparison
  matters.

## Phase 7: moderation and launch boundary

- Treat moderation and launch as separate operations even if Direct combines them in the UI.
- If submitting for moderation automatically starts delivery and launch is not explicitly authorized, do not submit. Report the coupling and wait for an explicit instruction either to launch or to submit and immediately suspend.
- When "submit and immediately suspend" is explicitly authorized, prepare the suspend action first, submit, suspend immediately, and verify zero/expected spend plus stopped campaign and group statuses.
- Immediately before an authorized launch, re-read budget, status, goal, and the Phase 6 experiment contract once more.
- After launch, confirm the campaign and intended groups are serving; do not assume the button succeeded.
- In the first monitoring window, inspect search terms or RSYA placements, spend, clicks, `bot_start`, first-day-open events, and attribution continuity. Add new exclusions only from evidence, not from unexplained bulk guesses.

## Phase 8: reporting acceptance

Do not treat a dashboard column as implemented because its label exists. For every new
funnel stage, prove the entire chain on one test participant: browser or bot action, one
idempotent database event, aggregation into the correct Start cohort, internal report payload,
and final Telegram table. Repeat the action and verify that unique-user counts do not grow.

Use `НД` when the signal was not instrumented or linked for that reporting date. Use `0` only
after the production event path is known to be active. Never silently omit an agreed stage.
Keep messenger in storage for detailed analysis. Show device as phone/desktop and entry method
as button/QR directly under their parent stages in the daily funnel.

For edabalans.ru, day-one reading depth is `page_progress` at 25/50/75/100. Video depth is
`video_engaged`, `video_progress` at 25/50/75, and `video_complete` as 100. The daily Telegram
report has exactly two messages: (1) one Direct message with an RSYA table and a Search table,
each containing its total and ad rows; (2) one complete acquisition path. The acquisition path
uses CTA/QR from the report date and accepts its first real Start plus later actions only before
the next 03:00 Moscow cutoff. Do not mix in a separate calendar-Start cohort.

The complete path must retain this registry in order: Direct clicks; Direct/Metric sessions on
the landing; phone and desktop session subrows; total recorded messenger entries; button and QR
subrows; confirmed Start; day-one open; day-one reminder sent; open within three hours after the
reminder; page 25/50/75/100; video start and 25/50/75/100; end-of-day CTA; confirmed subscription.
Columns are count, conversion from the logical parent stage, and conversion from the ad click.
Call the first two values clicks and visits, not people: they are not unique persons.

Show the exact period in every title. Direct spend/clicks cover 00:00–23:59 Moscow; attributed
Start and subsequent actions are accepted until 03:00 the next day. Show daily spend separately
from the current calendar week's configured budget, spend, and remaining amount, all read through
the Direct API. A combined daily expense must never be presented as one campaign's budget.

## Current edabalans.ru defaults

Defaults are not permanent decisions; always prefer the latest recorded brief.

- Never launch without Sergey's direct command.
- Keep Search and RSYA as separate campaigns.
- Primary early funnel goal is `bot_start`; purchases have a long cycle and are not the first creative-test decision metric.
- Preserve `yclid` and UTM data through the landing, messenger start, intensive progress, and payment path.
- Do not exclude menu/recipe intent from RSYA by default: Sergey may use it as a re-education entry.
- Desktop stays available unless a specific test says otherwise; QR attribution must be measurable separately.
