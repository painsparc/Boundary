# Resolution status

All items below, plus the additional findings from the follow-up pipeline analysis, are fixed and covered by `tests/test_boundary.py`.

| # | Issue | Fix | Regression test |
|---|-------|-----|-----------------|
| 1 | Internal-fraud runtime disagrees with policy | Not reproducible on the committed policy; root cause was `/save-policy` overwriting blocks with unvalidated, UI-generated rules. Saves now merge, validate and are audited; explanations show `policy_rule` vs `fallback_used`; policy hash is in every response and audit record | `test_bug1_*`, `test_save_merges_*` |
| 2 | Detection depends on field names | Key normalisation + alias table, value patterns (GOV-ids, PAN, SSN, Aadhaar with checksum), Presidio entity mapping, nested/list/numeric scanning | `test_bug2_*`, `test_nested_and_list_*` |
| 3 | Unsafe policies accepted | `policy.py` validates actions, routes and security invariants (no `ALLOW` of bank/government-id/medical/financial data below trust 0.90) on save **and** load; AI proposals are clamped | `test_bug3_*`, `test_generate_policy_*` |
| 4 | Unsupported combinations silently BLOCK everything | Unknown routes and unconfigured pairs return 422 with guidance; `/routes` drives the UI | `test_bug4_*` |
| 5 | Linkage risk not re-checked after transformation | Final payload re-assessed; exposed quasi-identifiers are generalised/blocked until within `MAX_RESIDUAL_RISK`; `overall_risk` now describes the output | `test_bug5_*` |
| 6 | Stale committed outputs | `src/generate_examples.py` regenerates them; a test fails if they drift from the policy hash | `test_bug6_*` |

Additional fixes: fail-closed unknown actions, strictest-rule-wins precedence, `MASK`/`GENERALIZE` crashes and literal `"Generalized"` output, Presidio false positives (score threshold, ignored/low-risk entities), semantic scan on any text field with an offline lexicon fallback, null/case-insensitive linkage, request-level audit records, atomic locked policy writes, restricted CORS, admin-endpoint protection, `/health` 503 and `/protect` 422 handling, Flutter stale-rule/error-handling fixes, tracked `__pycache__`/audit log removed, `.gitignore` added.

---

# Original report

# Boundary — Bug Findings, Impact & Fix Plan

## 1. BUG: Runtime Policy Mismatch in Internal Fraud Investigation

### Scenario

* Destination: `internal_fraud_system`
* Purpose: `fraud_investigation`
* Input contains `bank_account` and `government_id`.

### Expected According to Repository Policy

```text
bank_account  → ALLOW
government_id → BLOCK
```

### Actual Observed Result

```text
bank_account  → BLOCK
government_id → BLOCK
```

### Why This Is a Bug

The configured policy and runtime behavior disagree. The system says the bank account is permitted for this context, but the running engine blocks it. This indicates a possible discrepancy in policy loading, policy lookup, engine decision, API handling, or frontend output.

### Why Harmful

This makes Boundary unpredictable. A security system needs to enforce the policy that was configured. Inconsistent enforcement can cause legitimate fraud-investigation workflows to lose required information and makes auditing and debugging difficult.

### How to Investigate

Check:

* Whether the application loads the same `policies.yaml`.
* Whether an old/stale policy file is loaded.
* Whether destination and purpose exactly match the YAML keys.
* Whether the policy is actually found.
* Whether zero-trust fallback is being triggered.
* Whether the frontend displays the actual engine decision.
* Whether policies are reloaded after configuration changes.

### Fix

Make policy loading explicit and observable. Log:

```text
policy file path
policy version/hash
destination
purpose
policy_found
selected_action
fallback_used
```

Explicit policy decisions must be distinguishable from no-policy fallback decisions.

### Regression Test

Assert that:

```text
internal_fraud_system + fraud_investigation
```

preserves `bank_account` and blocks `government_id`, according to the current policy.

---

## 2. BUG CANDIDATE: Sensitive Fields May Depend on Exact Names

### Test

Replace:

```text
bank_account
government_id
```

with:

```text
account_number
gov_id
```

while keeping the same destination, purpose, and sensitive values.

### Why We Are Testing This

The engine has explicit high-risk handling for `bank_account` and `government_id`. We need to determine whether changing field names changes the security decision.

### What Would Constitute a Bug?

If `bank_account` is blocked but `account_number` containing the same sensitive value is allowed, that is a security bypass.

### Why Harmful

Real applications use different naming conventions such as:

```text
account_number
account_no
acct_no
accountNumber
beneficiary_account
gov_id
national_id
identity_number
```

Sensitive information should not become safe simply because the JSON key was renamed.

### Fix

Use multiple detection signals:

```text
field name
+
value pattern
+
Presidio/entity detection
+
semantic/context detection
```

Normalize field names and support configurable aliases.

Run the renamed-field test before classifying this as a confirmed bug.

---

## 3. BUG: Unsafe Policies Can Potentially Be Saved

### Problem

The policy-management API accepts policy rules. A dangerous policy could theoretically permit `bank_account` or `government_id` to an untrusted destination.

### Why Harmful

Boundary exists to protect sensitive information. If an API caller can configure `government_id` or `bank_account` as `ALLOW` for an untrusted destination, the security boundary becomes dependent on whoever submits the policy.

Potential causes include:

* compromised client
* malicious administrator
* buggy frontend
* incorrect AI-generated policy

### Fix

Add server-side security invariants.

For example, prevent:

```text
government_id → ALLOW
bank_account  → ALLOW
```

when the destination is `third_party_llm`, unless an explicitly authorized override mechanism exists.

Frontend warnings are not sufficient; the backend must enforce the rule.

### Better Architecture

```text
AI policy generation
→ schema validation
→ security-invariant validation
→ human review
→ save
```

---

## 4. DESIGN/CONFIGURATION ISSUE: Unsupported Destination-Purpose Combinations

### Observed

The UI allows destinations and purposes to be selected independently.

Examples:

```text
third_party_llm + fraud_investigation
marketing_analytics + fraud_investigation
```

can be selected even though no explicit policy exists.

### What Happens?

Boundary uses its zero-trust fallback, so high-risk fields become `BLOCK`.

### Classification

This is not necessarily a security bug because the zero-trust fallback may be intentional.

The issue is that the UI does not clearly tell the user that no policy exists for the selected combination.

### Why Harmful

Users may think Boundary evaluated a configured policy when it actually used fallback behavior, producing confusing and unexpected outcomes.

### Fix

**Frontend:**

* Show only valid purposes for the selected destination.
* Clearly indicate when fallback behavior is being used.

**Backend:**

* Validate the destination-purpose combination.
* Reject unsupported combinations with a clear error such as:

```text
No policy configured for this destination/purpose.
```

---

## 5. SECURITY WEAKNESS: Linkage Risk Should Be Checked Again After Transformation

### Problem

Boundary calculates linkage risk from the original data, then transforms the data. The final payload may therefore have a different risk profile.

### Why Harmful

A transformation may reduce one identifier while leaving enough quasi-identifiers to identify an individual.

The system could therefore treat the transformation as safe while the final payload remains high-risk.

### Fix

Use a second evaluation stage:

```text
Raw data
→ detection
→ risk calculation
→ policy
→ transformation
→ final payload
→ sensitivity/linkage re-evaluation
→ safe output
```

If final risk remains too high:

```text
generalize further
OR
remove
OR
block
```

### Regression Test

Use a record containing:

```text
age
city
occupation
postal_code
region
```

Run the policy and verify that the final payload's linkage risk is below the allowed threshold.

---

## 6. BUG: Committed Outputs Can Become Inconsistent With Current Policies

### Problem

The repository contains example/generated outputs.

If `policies.yaml` changes but the example output is not regenerated, then:

```text
policy
≠
committed output
≠
runtime behavior
```

### Why Harmful

Developers and testers cannot reliably reproduce the documented behavior.

A committed output may appear to represent the current policy when it does not.

### Fix

Add regression tests comparing generated output against expected policy behavior.

Alternatively, automatically regenerate example outputs when policy configuration changes.

Include a policy version/hash in results so outputs can be traced to the exact policy version.

---

# 7. The Three Original Observations — Classification

| Observed Scenario                                                                | Classification                                                                                                                                                       |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `third_party_llm + fraud_investigation → bank BLOCK`                             | Expected zero-trust fallback, assuming no explicit policy exists.                                                                                                    |
| `internal_fraud_system + fraud_investigation → bank BLOCK + government_id BLOCK` | Potential runtime-policy bug: repository policy indicates `bank_account → ALLOW`, so the observed BLOCK needs investigation against the exact running configuration. |
| `marketing_analytics + fraud_investigation → bank BLOCK + government_id BLOCK`   | Expected zero-trust fallback, assuming no explicit `fraud_investigation` policy exists for `marketing_analytics`.                                                    |

---

# 8. Priority for Fixing

## HIGH

1. Investigate the internal-fraud policy mismatch.
2. Protect the policy-management API with server-side security invariants.
3. Test renamed sensitive fields for a detection bypass.

## MEDIUM

4. Recalculate linkage risk after transformation.
5. Validate destination/purpose combinations.

## LOW/MEDIUM

6. Keep committed outputs synchronized with policies and add regression protection.

---

# 9. Recommended Team Workflow

### Runtime Debugging

Investigate:

```text
internal_fraud_system + fraud_investigation
```

and determine exactly why:

```text
bank_account
```

becomes `BLOCK`.

### Security Testing

Run field-name variants:

```text
bank_account
account_number
account_no
acct_no
accountNumber
```

and:

```text
government_id
gov_id
national_id
identity_number
id_number
```

Determine whether renamed fields bypass protection.

### Policy/API Testing

Inspect `/save-policy` and determine whether unsafe:

```text
bank_account → ALLOW
government_id → ALLOW
```

policies can be persisted.

### Privacy/Risk Testing

Test whether linkage risk is recalculated after transformations.

---

# 10. Required Format for Each Confirmed Bug

Every confirmed bug should contain:

```text
BUG ID

TITLE

REPRODUCTION
1.
2.
3.

EXPECTED
...

ACTUAL
...

ROOT CAUSE
...

WHY HARMFUL
...

FIX
...

REGRESSION TEST
...
```

---

# Key Architectural Improvement

Boundary should produce an auditable decision trace for every field:

```text
INPUT
→ DETECTED ENTITIES
→ FIELD SENSITIVITY
→ LINKAGE RISK
→ DESTINATION TRUST
→ PURPOSE SCOPE
→ SELECTED POLICY
→ ACTION
→ TRANSFORMED VALUE
→ FINAL RISK CHECK
→ OUTPUT
```

This would make discrepancies such as a `bank_account` BLOCK despite an ALLOW policy immediately diagnosable.
