---
name: add-aws-type
description: Add (or update) a collected AWS resource type in the aws_core plugin — manifest entry, model with the mandatory tags field, schemas + migration, unit tests, the live trial run, and release. Use whenever aws_core should start collecting a new AWS service type, or when changing what an existing type collects. Never ship a type blind.
allowed-tools: Read Write Edit Glob Grep Bash(git *) Bash(uv *) Bash(scripts/*) Bash(docker *) Bash(python *)
argument-hint: <aws-service-type e.g. sns_topic> [--update]
---

# Add an AWS Type to aws_core

> **Skill source-of-truth.** Canonical location: `tap_plugin/aws_core/skills/add-aws-type/SKILL.md`
> (ships in the wheel — the install carries it, per the tests-in-wheel AI-surface posture).

You are wiring one new collected AWS resource type through every layer of the
`aws_core` plugin. The 16 correctly-wired types are the reference corpus; the
**motivating scar is v0.4.0's `secrets_manager_secret`**, which shipped blind —
no live instance was ever collected before release — and carried a bug that
rejected entire GRIFT batches on any account with one secret (step 2 names it).
The whole point of this checklist is that step 5 makes that impossible to repeat.

Work happens from the command line in a dev checkout of
`tap-plugin-aws-core` (e.g. `_dev-plugins/aws_core/` inside a TAP session
worktree), on a branch. Building a new AWS type is developer/build-time
activity: live AWS access uses local developer credentials (AWS_PROFILE /
env), NOT the plugin's runtime secret envelopes.

## Step 1 — Manifest entry (`collectors/boto3_collector/aws_resource_manifest.json`)

Add the entry: `entity_type` (`aws_core__aws_<type>`), `service` (boto3 service
name), `scope` (`regional` | `global`), `source`, `why` (one honest sentence —
what relationship or risk does collecting this illuminate?), `items_path`,
`natural_key` (an ARN or the service's canonical id — the node is identified
by it, and it must be the field the model declares as its `NATURAL_KEY`), `fields` (model field → jsonpath), `edges`, and the three
declarations below. The schema requires all three, so an entry without them
fails manifest load.

**`sensitivity` — where the raw response may carry sensitive values**
(`req-aws-collector-manifest-6`). Do this for every call the entry makes (the
enumerate op, every `hydrate` op, every call inside the `custom_fn`):

1. Walk the botocore output shape and list every member with the `sensitive`
   trait. In the web container:
   `uv run --no-sync python -c "import botocore.session as b; m=b.get_session().get_service_model('<service>'); print(m.operation_model('<Op>').output_shape)"`,
   then recurse through `.members` / `.member` / `.value` checking
   `shape.metadata.get('sensitive')`. Each hit is a location with
   `"evidence": "botocore_sensitive"`.
2. Read the shape (and the `custom_fn`) for what botocore does not flag and add
   locations with `"evidence": "reviewer_judgement"`: environment/variable maps,
   templates, policy documents, external ids, header values, email addresses,
   operator descriptions, error text, and tag values wherever they ride inside
   the item (the tag lane's `from` path, or `_hydrate.tags` for the service lane).
3. Declare `reviewed_may_contain` with `{path, category, reason, evidence}`
   locations (paths in the manifest dialect, rooted at the yielded item), or
   `reviewed_none_known` — both with a `basis` naming what you read and the date.
4. If you have not done this, declare `{"status": "unreviewed"}`. That is an
   honest, allowed state, and it forces `"persist_configuration": false` (the
   schema rejects an unreviewed entry that persists: nobody has looked at what
   it returns, so storing it could store a secret). Never guess,
   and never omit the block.

For an `aws_op` entry, `test_boto3_collector_sensitivity.py` fails if any
botocore-`sensitive` member is left undeclared, or if a declared path does not
exist in the shape. A `custom_fn` entry is checked only by your reading.

**`persist_configuration` + `persist_configuration_why` — whether the node's
`configuration` is stored** (`req-aws-collector-field-projection-7`).

- If `sensitivity.status` is `unreviewed`, the flag is `false`. The schema
  rejects `true` (`req-aws-collector-manifest-7`).
- If `sensitivity` lists any `credential` location, set
  `"persist_configuration": false`, and make the reason name the location:
  `"Off: <Op> returns <path> verbatim, and <why that is a credential>."`
- Otherwise `true`, with a reason saying what the stored configuration carries
  that the typed fields do not.
- Persisting an entry that has a credential location is a known, reviewed risk
  that needs the owner's ruling. The test suite fails as shipped if any
  credential-bearing entry is persisted.
- `false` stores `configuration: {}`. Before choosing it, confirm that nothing
  the type needs is read back from the stored blob: typed fields, tags and edges
  are always derived from the in-memory envelope, so they are unaffected.

**STOP and ask the requester before choosing the flag** (whoever asked for the
type owns the risk of storing what it returns), when
adding or updating an entry and any of these is true:

- (a) the status would be `unreviewed`;
- (b) `sensitivity` lists any `credential` location;
- (c) you want `persist_configuration: true` and `sensitivity` lists any
  `reviewed_may_contain` location, of any category.

Do not pick the flag yourself in these cases, even where the rules above
already name a default. For (a) the flag is `false`, so the question is whether
to review the shape now or ship the entry unreviewed and not stored. Send the
person who asked for the work:

1. the entity type and the calls it makes (the enumerate op, each hydrate op,
   and the `custom_fn`);
2. the sensitivity status, and each location as `path`, `category`, `reason`
   and `evidence`, or for (a) why the review was not done;
3. the flag you propose and the `persist_configuration_why` you would write,
   including which typed fields, tags and edges still carry the facts the type
   needs if the flag is `false`.

Then wait for their answer and write what they decide. The requester can
always keep an entry off. They cannot on their own authorize storing a
`credential` location: that stays the owner's ruling (above), and
`test_shipped_credential_entries_are_all_off` fails until the owner changes it. Record the decision in
`persist_configuration_why` ("Ruling <date> (<who>): ..."). If you are a
subagent, hand the question back to your caller, who then asks the user. A
subagent must not answer it.

- `source`: prefer a declared `aws_op` (one list call, engine-paginated). Use a
  `custom_fn` in `customfns.py` ONLY when one logical resource needs multiple
  calls (describe fan-out, tag side-fetch, cross-join) — see
  `sqs_queues_described` / `apigateway_http_apis_detailed` for the shape and
  the per-item graceful-degradation discipline (`AccessDenied` on a sub-call
  degrades that slot, never kills the run).
- Validate against `aws_resource_manifest.schema.json` (the manifest unit tests
  do this; `manifest_version` only bumps on format changes, not entries).

**The tag-strategy decision (do not skip; this is settled, clever machinery —
pick the right lane per AWS's tagging surface for the service):**

| Strategy | When | Manifest shape |
|---|---|---|
| `rgta` | The resource type is covered by Resource Groups Tagging API and the item carries a joinable ARN | `"tags": {"source": "rgta", "join": {...}}` — tags land via the per-run RGTA sweep, joined by ARN (e.g. `lambda`) |
| service side-quest | RGTA excludes the type (e.g. IAM roles) but the service has a tag-list op | `"tags": {"source": "service", "op": ..., "params": ..., "path": ..., "shape": "list_kv"\|"map"}` — runs through the hydrate seam, so denials surface as `HYDRATE_GAP`, and normalizes via `normalize_tags` |
| projected field | A `custom_fn` already fetched tags while assembling the item | `"tags": "<path>"` inside `fields` (e.g. `"_tags"` for sqs, `"UserPoolTags"` for cognito) |

All three converge on ONE canonical `tags` field: a flat `{str: str}` map,
`{}` when untagged (a normal fact, never an omission). New wire shapes (ECS
lowercase kv, WAFv2 wrapped) extend the `normalize_tags` enum — never a
per-service loop.

## Step 2 — Model (`models/<type>.py`)

Copy the shape of a recent collected model (`sqs_queue.py` is clean): `BaseModel`
subclass, `ENTITY_TYPE = "aws_core__aws_<type>"` (== `db_table`), `ENTITY_NAME`,
`ENTITY_DESCRIPTION`, `ENTITY_ICON` (then run the `get-aws-icons` skill),
`DEFAULT_DIMENSIONS = {"tap.cloud": "aws"}`, `DEFAULT_DISPLAY`, fields,
`get_name`, `__str__`.

**THE TRAP (v0.4.0, named):** the collector emits `tags` on EVERY node
unconditionally — `batch.node_envelope` writes `"tags": tags or {}`, contract
"never omitted". A model without a `tags` field is therefore rejected wholesale
at GRIFT import: core validates the payload against the model's create schema
with `additionalProperties: false`, so the undeclared `tags` key fails the whole
batch. `SecretsManagerSecret` shipped exactly this way in v0.4.0 and broke
collection for any account with ≥1 secret. **Every collected model MUST declare:**

- field: `tags = models.JSONField(default=dict, blank=True)`
- `FIELD_CRUD_SCHEMA`: `"tags": {"type": "object"}`
- `FIELD_VALIDATION_SCHEMA`: `"tags": {"validation": "jsonschema", "schema": {"type": "object"}}`
- membership in `tests/test_aws_core_tags_field.py::_COLLECTED_MODELS` (the
  always-on guard for exactly this).

Same discipline for `configuration`: JSONField + both schema entries. Every
node payload carries the key; it is the full envelope, or `{}` when the entry's
`persist_configuration` is false.

## Step 3 — Schemas + migration

Every field the manifest projects MUST appear in `FIELD_CRUD_SCHEMA` **and**
`FIELD_VALIDATION_SCHEMA` (schemas are the import gate; the collector performs
no coercion — a projected field missing from the schema is the same
reject-the-batch failure as the tags trap). `CREATE_REQUIRED = ["name"]`.
Register the model in `models/__init__.py` and `tap-plugin.toml` `[models]`,
then generate the migration (from a TAP session worktree:
`scripts/dc exec web uv run python manage.py makemigrations aws_core`) and eyeball
it — one additive `CreateModel`, nothing touching existing tables.

## Step 4 — Unit tests (cheap, always-on)

In `tap_plugin/aws_core/tests/` (in-package; the wheel carries them):

- `custom_fn` / transform tests with faked boto3 clients — follow
  `test_boto3_collector_new_service_types.py` (enumeration shaping, edge-key
  derivation, per-item degradation on denial).
- Payload-vs-schema: build a realistic raw item, run `project_item` +
  `node_envelope`, validate the payload against the model create schema with
  `additionalProperties: false` (reuse `_create_verb_schema` /
  `_prepare_null_payload` from `test_trial_run_live.py`). This is the offline
  half of the trial-run assertion and runs in every lane.
- **When `persist_configuration` is false:** plant a secret-shaped canary at
  each credential location in the canned response of
  `test_boto3_collector_slice.py`. Then add the type to `_OFF_CASES` with
  `(entity_type, natural_key, canary, typed_field, expected_value)`.
  - `test_credential_canary_is_not_persisted` proves the canary is in neither
    the GRIFT document nor the stored row or its history rows.
  - `test_flag_is_what_keeps_the_canary_out` proves the canary really is in the
    canned response, and that the flag is what keeps it out.

## Step 5 — THE TRIAL RUN (never ship a type blind)

The executable half of this skill:
`tap_plugin/aws_core/tests/test_trial_run_live.py` (its module docstring is the
operator runbook — env vars, exact commands, credential seam, sweep).

1. Add a `TrialTypeSpec` for the new type: a provisioner that creates the
   CHEAPEST possible live instance via boto3, tagged through the service's
   native tag surface with `tap:trial=sacrificial` + `tap:trial-session=<run>`,
   name-prefixed `tap-trial-`, with an instant teardown. If the type cannot be
   torn down cleanly (KMS's 7-day deletion floor, CloudTrail's S3 prerequisites),
   register it with a `deferred_reason` naming the caveat honestly instead.
2. **Get human approval for what will be provisioned** — the harness enforces
   this: nothing runs unless a human lists the type in `TAP_AWS_TRIAL_TYPES`.
   State the expected cost/residue when asking.
3. Run it (write credentials = local developer AWS credentials, or the
   `trial_provisioner` envelope once that has passed /manage-secret review;
   NEVER the read-only `boto_collector` envelope). Attach the
   `handoff/trial-provisioner-policy.json` policy to the identity used.
4. Green means: the live resource appeared through the real collection path,
   its emitted payload validates against the model schema exactly as GRIFT
   import will, and the trial tags round-tripped through the tag strategy
   chosen in step 1.
5. Confirm teardown (the run deletes in `finally`; a crashed run is cleaned by
   `TAP_AWS_TRIAL_SWEEP=all` — RGTA find-by-tag, delete).

## Step 6 — Release

`release-plugin.sh` from the plugin repo (runs the gates, tags, builds); then
bump the pin in every consuming boot record (e.g. the samsite profile's
boot-record BOM) so the new version actually boots somewhere. A type is DONE
when: trial run green, unit tests green in the plugin's CI lane against
core-main, released, pins bumped — in that order.
