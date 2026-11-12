# AWS Core collector — cross-account access handoff

This directory is the operator handoff for pointing the AWS Core collector at a
**running service in an AWS account you do not own** (e.g. a partner's app).
It implements the industry-standard cross-account pattern: the account owner
creates a read-only IAM **role**, and the collector **assumes** it via STS to
get short-lived credentials — no long-lived keys ever cross the boundary.

Spec: `plugins/aws_core/specs/spec-aws-core-secrets.md`
(`req-aws-core-secret-aws-assumed-role`).

Artifacts:

- `cross-account-role.yaml` — CloudFormation template (the default, shortest path).
- `cross-account-role.tf` — Terraform equivalent (only if the partner already uses Terraform).

Both create the **same** role: trust = your collector principal + a required
External ID; permissions = AWS-managed `SecurityAudit` (read-only config, no
data-plane object reads).

A fourth artifact — `collector-principal-policy.json` — is the *operator*-side
policy (yours, not the partner's): it goes on your collector IAM user.

A fifth artifact — `trial-provisioner-policy.json` — is the least-privilege
policy for the **trial-run provisioner** (see
`tap_plugin/aws_core/tests/test_trial_run_live.py` and the `add-aws-type`
skill): a *developer-side* identity that creates, tags, and deletes the
sacrificial `tap-trial-*` resources a live trial run needs. It is deliberately
NOT the collector principal — the collector envelope
(`aws_core/boto_collector`) is SecurityAudit read-only and must never gain
write actions. The policy fences writes two ways: creates require the request
to tag `tap:trial=sacrificial` (`aws:RequestTag`), and deletes only reach
resources already bearing that tag (`aws:ResourceTag`). Caveats: services that
reject tag-condition keys on a given call would need that condition relaxed
per-service (verify on first live use), and API Gateway v2 grants are
expressed as `apigateway:POST/GET/DELETE` (its IAM model is verb-on-path, not
per-resource actions). If the trial run ever moves onto a tap-secrets envelope
(scope `aws_core`, key `trial_provisioner`, kind `aws_static_access_key`),
that wiring goes through the /manage-secret review first.

---

## Before you send anything (TAP operator, one-time setup)

1. **Mint a dedicated collector IAM principal** in *your* account — an IAM user
   `tap-aws-core-collector` whose *only* permission is assuming the partner's
   role. Attach the inline policy in **`collector-principal-policy.json`**,
   replacing `<PARTNER_ACCOUNT_ID>` with the partner's account id (add more role
   ARNs to the `Resource` list as you onboard more accounts).

   Its access key becomes the `base` credentials in the secret (below). Because
   it can do nothing but assume a read-only role, a leak is low-value.

2. **Generate an External ID** — any unguessable string, unique per partner.
   Keep it with the secret; you will hand a copy to the partner.

## What you send the partner

- The **collector principal ARN** from step 1 (e.g.
  `arn:aws:iam::111122223333:user/tap-aws-core-collector`).
- The **External ID**.
- One artifact: point them at `cross-account-role.yaml` (or the `.tf`).

## What the partner does (≈1 minute)

**CloudFormation (default):** AWS Console → CloudFormation → Create stack →
upload `cross-account-role.yaml` → paste the **collector principal ARN** and
**External ID** → check *"I acknowledge that this template may create IAM
resources"* → Create. (If you send a pre-filled console launch link, they just
review and click Create.)

**Terraform (if they already use it):** `terraform apply` with
`trustee_principal_arn` and `external_id` set.

Either way they read the read-only grant *before* accepting, and revoke by
deleting the stack / `terraform destroy`.

## What the partner sends back

The stack/apply **Outputs**:

- `RoleArn` → `data.role_arn`
- `AccountId` → `data.expected_account_id`
- plus the **region(s)** the service runs in → `data.region` / `data.regions_allowed`

## Wire it into the collector secret

Drop `boto_collector.secret.json` under `TAP_SECRETS_ROOT` (scope `aws_core`,
key `boto_collector`), kind `aws_assumed_role`:

```json
{
  "scope": "aws_core",
  "key": "boto_collector",
  "kind": "aws_assumed_role",
  "description": "Cross-account read-only role for the partner's running app.",
  "data": {
    "role_arn": "arn:aws:iam::<PARTNER_ACCOUNT_ID>:role/TapAwsCoreCollectorReadOnly",
    "external_id": "<the External ID you generated>",
    "expected_account_id": "<PARTNER_ACCOUNT_ID>",
    "base": {
      "access_key_id": "<collector principal access key>",
      "secret_access_key": "<collector principal secret key>"
    },
    "regions_allowed": ["us-east-1"]
  }
}
```

`manage.py collector selftest` (or the collector's self-test) then proves the
whole chain: it assumes the role, calls `GetCallerIdentity`, and asserts the
landed account equals `expected_account_id`.

> Never commit a real `*.secret.json`. Secret material (base keys, External ID)
> is redacted in all collector logs and errors.

## The collector's own policy (instead of SecurityAudit + ReadOnlyAccess)

`collector-policy-01.json` … `collector-policy-NN.json` are generated from what the collector can call: every
operation the manifest names (list, per-parent, tag, hydrate, detail), the operations its Python makes, mapped to IAM
actions through AWS's Service Authorization Reference. They are read-only; an explicit `Deny` in the first file
(`NeverReturnSecretsOrContents`) blocks the actions that return secret values or the contents of a resource, so no
other policy on the role can grant them. Regenerate after any manifest change:

    uv run python -m tap_plugin.aws_core.collectors.boto3_collector.iam_policy --refresh   # network; AWS's reference
    uv run python -m tap_plugin.aws_core.collectors.boto3_collector.iam_policy --write

Attach them with `cross-account-role-custom.tf` (Terraform) or `create-collector-policies.sh` (any other tool; the
documents together exceed CloudFormation's inline template limit). IAM allows ten managed policies on a role by
default; the set uses nine. `iam_policy.unverified()` lists the operations whose action name is the default
`<prefix>:<Operation>` because AWS's reference data does not name one; they are checked by the policy simulator,
not yet by a live round trip with the role.

### Residual access the policy cannot remove

Two services authorise their control-plane reads with an action that also covers data, and IAM has no separate action
or condition to split them. The policy grants them because the inventory needs them; the managed policies
`SecurityAudit` and `ReadOnlyAccess` grant the same. A customer who cannot accept either removes the statement and
loses that inventory (the collector reports the gap and keeps what it stored; it never deletes on a refused read):

- `cassandra:Select` — Amazon Keyspaces lists keyspaces and tables through it, and it also runs `SELECT` on a table.
- `apigateway:GET` — all API Gateway control-plane reads, including `GetApiKey` with `includeValue=true`, which returns
  the key value. The collector never sets `includeValue`; the role could.
