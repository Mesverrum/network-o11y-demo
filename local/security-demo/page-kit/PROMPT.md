# Build: Halvorsen Motors SOC investigation console

Draft only. Do not publish, share or make this page public. It runs on this stack (marcnetterfield1) for an internal demo.

**Audience safety.** Halvorsen Motors is a made-up automaker and every record is synthetic. Do not name any real car company, real customer or real person anywhere on the page, in copy, examples or placeholders. If you need an example name, use one from the data files.

## 1. What this is

A single-page investigation console for a security detection team at a large automaker. It replaces eight Grafana dashboards (folder "Halvorsen Motors SOC (demo)", uids `hm-*`) with one guided app. The dashboards already hold the right queries and wording. The page adds what dashboards cannot do: a case that remembers what the analyst found, one step at a time, verdicts that drive a recommendation, a hop map that grows as the analyst follows an attacker, and a report at the end.

"Paint by numbers" is the brief. An analyst who has never seen this environment should always know what to look at, what bad looks like, and what to click next.

## 2. Data you will receive

Seven JSON files follow this prompt, one per message. Together they are one object; merge them by concatenating every `workflows` array in order and keeping `meta` and `link_params` from the first file. Embed the merged object as `const KIT` verbatim. Do not retype queries or card text.

| File | Holds |
|---|---|
| `02a-meta-triage-case.json` | `meta` (datasource, replay note, query notes), `link_params`, the `triage` workflow (six leads) and `case` (timeline) |
| `02b-wf1.json` to `02g-wf6.json` | one workflow each: WF1 sign-in, WF2 endpoint, WF3 lateral movement, WF4 exfiltration, WF5 plant floor, WF6 vehicle API |

Shape of a workflow: `id`, `title`, `description`, `variables[]` (name, label, default, optional `choices`), `intro[]` markdown, `leads[]` (triage only), `steps[]`, `decide`.

- A step has `n`, `title`, `card` (`look`, `bad`, `if_bad`, `if_clean`, optional `links`) and `evidence[]`.
- An evidence item has `kind` (`stat`, `table`, `timeseries`, `logs`), `title`, `expr` (LogQL, a string or an array for several series), `query` (`instant` or `range`), and optionally `help`, `unit`, `thresholds`, `legend`, `value_column`, `links`.
- A table link is `{column, label, workflow, params}`. Each param value says where it comes from: `cell` is the clicked value, `row.<col>` is another column in that row, `var.<name>` is the current workflow variable, `literal:<x>` is fixed.
- Markdown may contain `[[Label]]`. That is a link: find the entry with the same `label` in the sibling `links` array and render a button that opens that workflow with those params.
- `decide` has `markdown`, optional `links`, and `rule`: `verdict`, `when` (boolean over step verdicts, `s1` means step 1 was marked Suspicious), optional `also`, `next_if_true`, `close_if_false`.

## 3. Queries

All data comes from the Loki datasource `{"type":"loki","uid":"grafanacloud-logs"}` on this stack. No other external call and no runtime CDN.

- Before running an `expr`, substitute `$__range` with the selected range as a duration in seconds (`10800s`), `$__interval` with the step you chose for that chart, and every `$name` or `${name}` with the current workflow variable. Regex special characters in user values are fine as is; the values are plain hostnames and user names.
- `instant` queries return one row per label set. A `table` shows every label as a column plus the value under `value_column`, sorted by value descending. A `stat` shows the single value, colored by `thresholds` (the highest `from` the value reaches wins; null `from` is the base color). No result means 0 for a stat and "Nothing found in this range" for a table.
- `range` queries drive `timeseries` (bars when `style` is `bars`) and `logs` (oldest first, show the time and the formatted line, nothing else).
- Run the queries for the visible step only, and cache results per step and variable set until the range changes.

## 4. Layout

Dark, quiet, built for a long shift. Grafana's own type and colors: Inter for text, a monospace for entities and queries. Red, orange and green only for verdicts and thresholds, never for decoration. Generous whitespace, one idea per region.

- **Top bar:** title, the time range (last 1h, 3h, 6h, plus a **Latest attack cycle** button), the current case name, and a small "synthetic data" tag.
- **Left rail (always visible): the case.** Entity chips grouped by kind (users, hosts, IPs, assets, API keys), the workflow trail ("WF2 > WF3 hop 2 > WF5"), the verdict log, and open actions. Clicking a chip opens the best workflow for that kind.
- **Main area:** one of five views, chosen from tabs: Triage, Workflow, Hop map, Timeline, Report.

**Latest attack cycle:** the scripted intrusion starts at the top of every UTC hour and runs about 30 minutes. If the current UTC minute is 32 or later, use this hour; otherwise use the previous hour. Range is that hour's start to start plus 35 minutes. Show a one-line note explaining the replay (from `meta.replay`).

## 5. Views

**Triage.** Six lead cards in the order given (A to F). Each card shows the lead title, `why`, a big live counter (the stat, colored by its thresholds), and the top five rows of its table. Green counters fade back. Clicking a row value starts a new case named after that entity (or adds to the open case if one exists; ask which with two buttons), records the lead, and opens the linked workflow with params filled.

**Workflow.** A stepper.

- Header: workflow title, `description`, the variables as editable chips, and a progress strip with one dot per step plus Decide. Dots show the verdict color once set.
- One step is open at a time. The card sits on the left (Look at, Suspicious if, If suspicious, If clean, written as four short labelled lines). Live evidence sits on the right.
- Under the evidence: three buttons, **Suspicious**, **Clean**, **Can't tell**, plus a one-line note field. Pre-select a suggestion, never a final answer: suggest Suspicious when any stat is at its red step or a `logs`/`table` on that step returns rows that the card calls bad; otherwise leave unselected. The analyst confirms with one click. Saving a verdict advances to the next step.
- Table cells with a link render as buttons. Clicking one adds the value to the case as an entity, records the breadcrumb ("from WF2 step 3"), and opens the target workflow with the params resolved.
- **Ask Assistant** (small, secondary) on each step: send the step title, card text and a compact summary of the evidence rows, and show the reply under the evidence as "Assistant's read, check it". If inline Assistant is not available, hide the button.
- **Decide** step: evaluate `rule.when` against the saved verdicts (`can't tell` counts as not suspicious, and say so). Show the verdict sentence large, the steps that drove it, the `markdown` with its `[[links]]` as buttons, and the "Do these now" items as a checklist saved to the case. If the rule is false, show `close_if_false` and a **Close lead** button. Show `rule.also.say` when its condition holds.
- WF5 keeps its safety text at the top of every step, not just once.

**Hop map** (fed by WF3). Every time the analyst follows a destination from WF3 step 4, add a node for the destination and an edge from the current hop, labelled with the account and port or logon type from that row. Node color is the worst verdict saved for that host across WF3 steps 1 to 3. Clicking a node makes it the current hop and opens WF3 step 1 for it. Under the map, the containment list: every node, its accounts, and a checkbox. Add an **Auto-trace** button that runs the two step 4 queries recursively from the current host, breadth first, up to six hops and forty nodes, and draws the result in a lighter style marked "auto-traced, not reviewed" until the analyst opens each node. Plant zone hosts (names starting `JMP-`, `EWS-`, `HMI-`, `PLC-`) get a distinct outline.

**Timeline.** One merged log for every entity in the case: `{service_name=~"secdemo-.+"} |~ "(?i)(<entities joined by |>)"`, escaped. Group into swimlanes by `service_name`. Pull `technique_id` and `tactic` out of each JSON line when present and show them as chips. Above the lanes, a strip of ATT&CK tactics in kill-chain order (Initial Access through Impact, plus ICS Impair Process Control) that lights up for tactics seen. The first event across the case is labelled "earliest evidence".

**Report.** A generated markdown case report: case name, time range, entities by kind, the trail, each workflow's verdicts and notes, the Decide outcomes, open and done actions, and the earliest and latest events. A **Copy** button. Optionally **Draft summary with Assistant** writes a three-sentence executive summary above it, labelled as a draft.

## 6. State

Persist cases in per-user storage: a list of cases, each with id, name, created time, range, entities, trail, verdicts keyed by workflow, variable set and step, notes, checklist state and hop map. Reload restores the last open case and view. Provide **New case** and **Delete case**. If storage is not available, keep state in memory and say so in the rail.

## 7. Empty and failed states

- No data for a step: "Nothing found in this range." with a **Latest attack cycle** button. Never invent rows.
- Query error: show the error text small under the panel and keep the rest of the step usable.
- Counters show 0, not blank.

## 8. Done when

1. Triage loads live counters for all six leads.
2. Clicking `carlos.ortega` (or whoever Lead A shows) in Lead A opens WF1 with `user` set, and the case rail shows the user.
3. A full path works without typing: Lead B host to WF2, WF2 step 6 to WF3, WF3 step 4 hop to the jump host, then the engineering workstation, then the HMI, each hop drawn on the map; WF3 step 5 asset to WF5.
4. Decide on WF1 shows "Account compromised" when steps 1 and 2 are Suspicious.
5. Report copies a markdown case with every entity and verdict from that path.
6. No real company or person names anywhere.

Build it. Draft only. Do not publish or share.
