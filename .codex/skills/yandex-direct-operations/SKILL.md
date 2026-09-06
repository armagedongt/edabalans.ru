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

Record the hypothesis, primary metric, guardrails, and decision threshold before launch. Do not improvise the test after seeing early results.

- Use `bot_start` as the primary early decision metric. Use landing-to-bot conversion, CTR, and CPC to diagnose the funnel. Treat payments as delayed confirmation because the sales cycle is 30+ days.
- Change one variable at a time. For the first RSYA stage, keep one landing, headline, body, extensions, audience, placements, budget, and goal fixed; vary only the image across three separate ad IDs.
- Prefer simultaneous variants in one group so weekday and market conditions match. Before launch, record a fallback for allocation starvation: either extend the test within its fixed budget/time cap or move the under-served variant to a comparable sequential window and label the result lower-confidence.
- Do not choose a winner from one day, a trivial spend, or impressions alone. Derive the evidence threshold from the campaign's baseline CTR, landing-to-bot rate, target CPA, affordable maximum spend, and detectable effect. If those inputs are unavailable, pre-authorize a finite exploratory budget and label the outcome provisional rather than presenting a universal click or conversion quota as statistically final.
- Record both a maximum experiment spend and a calendar end date. Define stop-loss rules for zero conversions and for nonzero conversions that remain above the affordable CPA. A technically healthy variant may continue only within those caps; reaching either cap forces stop, extension approval, or a provisional no-decision result.
- After the image winner, test two or three headline/body packages while keeping the winning image and all campaign settings fixed. Test another landing only after the ad package has a stable signal.
- Record every material edit with timestamp, object IDs, old value, new value, reason, and test version. Never overwrite a historical creative inside an existing ad when comparison matters.

## Phase 7: moderation and launch boundary

- Treat moderation and launch as separate operations even if Direct combines them in the UI.
- If submitting for moderation automatically starts delivery and launch is not explicitly authorized, do not submit. Report the coupling and wait for an explicit instruction either to launch or to submit and immediately suspend.
- When "submit and immediately suspend" is explicitly authorized, prepare the suspend action first, submit, suspend immediately, and verify zero/expected spend plus stopped campaign and group statuses.
- Immediately before an authorized launch, re-read budget, status, goal, and the Phase 6 experiment contract once more.
- After launch, confirm the campaign and intended groups are serving; do not assume the button succeeded.
- In the first monitoring window, inspect search terms or RSYA placements, spend, clicks, `bot_start`, first-day-open events, and attribution continuity. Add new exclusions only from evidence, not from unexplained bulk guesses.

## Current edabalans.ru defaults

Defaults are not permanent decisions; always prefer the latest recorded brief.

- Never launch without Sergey's direct command.
- Keep Search and RSYA as separate campaigns.
- Primary early funnel goal is `bot_start`; purchases have a long cycle and are not the first creative-test decision metric.
- Preserve `yclid` and UTM data through the landing, messenger start, intensive progress, and payment path.
- Do not exclude menu/recipe intent from RSYA by default: Sergey may use it as a re-education entry.
- Desktop stays available unless a specific test says otherwise; QR attribution must be measurable separately.
