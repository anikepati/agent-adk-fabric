# DecisionTreeAgent — System Design & Architecture

**Version:** 3.0
**Author:** Sunil — Principal Engineer, Enterprise AI Architecture
**Status:** Production-Ready Component
**Last Updated:** April 2026

---

## 1. Design Philosophy

The DecisionTreeAgent is built on three non-negotiable principles.

**Deterministic execution.** The agent never calls an LLM. Given the same row data and the same YAML config, it produces the exact same output every time. This is critical for compliance workloads where auditability and reproducibility are requirements, not features.

**Single responsibility.** The agent does exactly one thing: take one row of data and one set of YAML rules, evaluate the rules against the row, and return structured decisions. It does not load Excel files. It does not batch rows. It does not execute API calls or write to databases. Those are responsibilities of other agents in the pipeline.

**Composability.** The agent communicates exclusively through `ctx.session.state` using namespaced keys (`dt:row`, `dt:decisions`, `dt:actions`). It can be placed inside any `SequentialAgent`, `ParallelAgent`, or `LoopAgent` pipeline without modification. Change the `state_prefix` to run multiple instances in the same pipeline without key collisions.

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    ADK Runner / Pipeline                         │
│                                                                  │
│  ┌─────────────┐    ┌──────────────────┐    ┌────────────────┐   │
│  │ Upstream     │    │ DecisionTree     │    │ Downstream     │   │
│  │ Agent        │───►│ Agent            │───►│ Agent          │   │
│  │              │    │                  │    │                │   │
│  │ Sets:        │    │ Reads:           │    │ Reads:         │   │
│  │  dt:row      │    │  dt:row          │    │  dt:actions    │   │
│  │  dt:config_* │    │  dt:config_*     │    │  dt:exceptions │   │
│  │              │    │                  │    │  dt:passed     │   │
│  └─────────────┘    │ Writes:          │    │  dt:decisions  │   │
│                     │  dt:decisions    │    │                │   │
│                     │  dt:actions      │    └────────────────┘   │
│                     │  dt:exceptions   │                         │
│                     │  dt:passed       │                         │
│                     │  dt:status       │                         │
│                     └──────────────────┘                         │
│                              │                                   │
│                     ┌────────▼────────┐                          │
│                     │   Internal      │                          │
│                     │                 │                          │
│                     │  ┌───────────┐  │                          │
│                     │  │ Config    │  │                          │
│                     │  │ Loader    │  │                          │
│                     │  └─────┬─────┘  │                          │
│                     │        │        │                          │
│                     │  ┌─────▼─────┐  │                          │
│                     │  │ Tree      │  │                          │
│                     │  │ Walker    │  │                          │
│                     │  └─────┬─────┘  │                          │
│                     │        │        │                          │
│                     │  ┌─────▼─────┐  │                          │
│                     │  │ Condition │  │                          │
│                     │  │ Evaluator │  │                          │
│                     │  │ (14 ops)  │  │                          │
│                     │  └───────────┘  │                          │
│                     └─────────────────┘                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Design

### 3.1 Component Map

The agent consists of four modules totaling approximately 290 lines of code.

```
dt_agent/
├── agents/
│   └── decision_tree_agent.py    # 120 lines — ADK BaseAgent wrapper
├── engine/
│   ├── evaluator.py              #  60 lines — operator registry + evaluation
│   └── walker.py                 #  55 lines — recursive tree traversal
└── models/
    └── schemas.py                #  55 lines — Pydantic v2 schemas
```

### 3.2 DecisionTreeAgent (agents/decision_tree_agent.py)

This is the ADK-facing component. It extends `google.adk.agents.BaseAgent` and implements `_run_async_impl`.

**Responsibilities:**
- Read `dt:row` and config source from `ctx.session.state`
- Load and validate YAML config via Pydantic
- Delegate evaluation to the tree walker
- Flatten results into `dt:actions` and `dt:exceptions`
- Compute `dt:passed` (boolean: zero exceptions = passed)
- Write all outputs back to state
- Yield a summary `Content` message for the ADK event stream

**What it does NOT do:**
- Call an LLM
- Load Excel files
- Execute API calls or database writes
- Batch multiple rows
- Handle retries or error recovery for downstream systems

```
_run_async_impl(ctx)
    │
    ├── 1. Read dt:row from state
    │
    ├── 2. Load config (3 sources, priority order):
    │       dt:config_yaml  → raw YAML string in state
    │       dt:config_path  → file path in state
    │       self.config_path → constructor default
    │
    ├── 3. walk_all(config.decision_trees, row)
    │       └── Returns: List[DecisionRecord]
    │
    ├── 4. collect_actions(decisions)
    │       └── Returns: List[ActionRecord] (flat)
    │
    ├── 5. Filter exceptions from actions
    │       └── Where endpoint contains "exception"
    │           or payload contains "exception_id"
    │
    ├── 6. Write to state:
    │       dt:decisions  = full tree traversal
    │       dt:actions    = flat action list
    │       dt:exceptions = exception actions only
    │       dt:passed     = len(exceptions) == 0
    │       dt:status     = "completed"
    │
    └── 7. Yield Content summary message
```

### 3.3 Condition Evaluator (engine/evaluator.py)

The evaluator is a stateless function that takes a `Condition` schema object and a row dict, and returns a boolean. It uses a flat dictionary of operator functions — no class hierarchy, no inheritance, no dynamic dispatch beyond a dict lookup.

**Operator Registry:**

```
OPERATORS = {
    "gt":         (left, right) → left > right
    "gte":        (left, right) → left >= right
    "lt":         (left, right) → left < right
    "lte":        (left, right) → left <= right
    "eq":         (left, right) → left == right
    "neq":        (left, right) → left != right
    "contains":   (left, right) → right in left
    "starts_with":(left, right) → left.startswith(right)
    "ends_with":  (left, right) → left.endswith(right)
    "is_empty":   (left)        → left is null or whitespace
    "regex":      (left, pattern)→ re.match(pattern, left)
    "is_null":    (left)        → left is None or NaN
    "is_not_null":(left)        → not is_null
    "between":    (left, low, high) → low <= left <= high
    "in":         (left, values) → left in values
    "not_in":     (left, values) → left not in values
}
```

**Operator categories by arity:**

| Category | Operators | Input signature |
|----------|-----------|----------------|
| Binary (left vs right) | `gt`, `gte`, `lt`, `lte`, `eq`, `neq`, `contains`, `starts_with`, `ends_with` | `(left_val, right_val, **kwargs)` |
| Unary (left only) | `is_null`, `is_not_null`, `is_empty`, `regex` | `(left_val, **kwargs)` |
| Kwargs-only | `between`, `in`, `not_in` | `(left_val, **kwargs)` — uses `low`/`high` or `values` |
| Compound | `and`, `or` | Recursive evaluation of child conditions |

**Type coercion strategy:**

```
1. Try float(left) vs float(right)
2. If either fails → fall back to str(left).strip() vs str(right).strip()
3. If left is None or NaN → return False for all comparison ops
4. Exception: eq(None, None) → True, neq(None, None) → False
```

**Compound condition evaluation:**

```
evaluate(CompoundCondition, row):
    if operator == "and":
        return all(evaluate(child, row) for child in conditions)
    if operator == "or":
        return any(evaluate(child, row) for child in conditions)
```

Compound conditions nest arbitrarily deep. An `and` can contain an `or` which contains another `and`. There is no depth limit.

### 3.4 Tree Walker (engine/walker.py)

The walker takes a `DecisionNode` and a row dict, and returns a structured decision record by recursively traversing the tree.

**Algorithm:**

```
walk_tree(node, row):
    1. result = evaluate(node.condition, row)
    2. branch = node.on_true if result else node.on_false
    3. action_output = serialize(branch.action, branch.endpoint, branch.payload, branch.set)
    4. record = {node_id, node_name, result, branch, action_output, children: []}
    5. if branch.next_decision exists:
           child_record = walk_tree(branch.next_decision, row)
           record.children.append(child_record)
    6. return record
```

**`walk_all` function:**

```python
def walk_all(trees, row):
    return [walk_tree(tree, row) for tree in trees]
```

Every tree in the config is evaluated for every row. Trees are independent — the result of one tree does not affect the evaluation of another. This is by design: business rules are evaluated exhaustively so the audit trail captures every decision.

**`collect_actions` function:**

Flattens the recursive tree result into a linear list of actions. Only actions where `action != "none"` are included. This flat list is what downstream agents consume.

```
Tree result (nested):                  Flat action list:
  ✓ amount_tier → api_call /flag  →    [{node: amount_tier, endpoint: /flag, ...},
      ✗ currency → db_update      →     {node: currency, set: {sub_tier: ...}}]
```

### 3.5 Pydantic Schemas (models/schemas.py)

The schemas serve two purposes: YAML validation at load time and type safety at evaluation time.

**Model hierarchy:**

```
DecisionTreeConfig
  └── decision_trees: List[DecisionNode]
        ├── id: str
        ├── name: str
        ├── condition: Condition  ←─── union of SimpleCondition | CompoundCondition
        ├── on_true: ActionBranch
        │     ├── action: "api_call" | "db_update" | "log_only" | "none"
        │     ├── endpoint, payload, set, method
        │     └── next_decision: Optional[DecisionNode]  ←─── recursive
        └── on_false: ActionBranch
              └── (same structure as on_true)
```

**Key design decisions:**

- `on_true` and `on_false` default to `action: "none"` when omitted. This allows branches that only contain `next_decision` without requiring an explicit `action: "none"` in the YAML.
- `DecisionTreeConfig` uses `model_config = {"extra": "allow"}` so additional top-level keys (like `dag` or `settings`) pass through without validation errors.
- Forward references (`DecisionNode` → `ActionBranch` → `DecisionNode`) are resolved by calling `model_rebuild()` after all classes are defined.
- Pydantic `model_validator` on `SimpleCondition` enforces operand requirements per operator at load time, not at evaluation time.

---

## 4. State Contract

### 4.1 Input State

Set these keys in `ctx.session.state` before the agent runs.

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `dt:row` | `Dict[str, Any]` | Yes | Single row of data. Keys are column names, values are cell values. |
| `dt:config_path` | `str` | Conditional | File path to YAML config. Required if `config_path` not set on constructor and `dt:config_yaml` not in state. |
| `dt:config_yaml` | `str` | Conditional | Raw YAML string. Takes priority over `dt:config_path`. Useful when another agent generates rules dynamically. |

### 4.2 Output State

The agent writes these keys after evaluation completes.

| Key | Type | Always Set | Description |
|-----|------|-----------|-------------|
| `dt:decisions` | `List[Dict]` | Yes | Full tree traversal results. One entry per tree, with nested `children` for `next_decision` paths. |
| `dt:actions` | `List[Dict]` | Yes | Flat list of all actions (excluding `action: "none"`). Each item includes `node_id`, `node_name`, `result`, `branch`, `action`, `endpoint`, `payload`, `set`. |
| `dt:exceptions` | `List[Dict]` | Yes | Subset of `dt:actions` where `endpoint` contains "exception" or `payload` contains `exception_id`. |
| `dt:passed` | `bool` | Yes | `True` if `dt:exceptions` is empty. `False` otherwise. |
| `dt:status` | `str` | Yes | `"completed"`, `"failed"`, or `"no_data"`. |
| `dt:error` | `str` or `None` | On failure | Error message when `dt:status` is `"failed"`. `None` on success. |

### 4.3 State Prefix

The default prefix is `"dt"`. Pass a different `state_prefix` on the constructor to avoid collisions when multiple DecisionTreeAgent instances run in the same pipeline.

```python
agent_a = DecisionTreeAgent(name="LoanRules",  state_prefix="loan",  config_path="config/loan.yaml")
agent_b = DecisionTreeAgent(name="ComplianceRules", state_prefix="comp", config_path="config/compliance.yaml")

# agent_a reads loan:row, writes loan:decisions, loan:passed, etc.
# agent_b reads comp:row, writes comp:decisions, comp:passed, etc.
```

---

## 5. YAML Config Schema

### 5.1 Minimal Config

```yaml
decision_trees:
  - id: "rule_1"
    name: "BB exceeds BC"
    condition:
      operator: "gt"
      left_column: "BB"
      right_column: "BC"
    on_true:
      action: "api_call"
      endpoint: "/update"
      payload:
        result: "Yes"
    on_false:
      action: "db_update"
      set:
        result: "No"
```

### 5.2 Nested Decision Tree

```yaml
decision_trees:
  - id: "amount_tier"
    name: "Amount classification"
    condition:
      operator: "gte"
      left_column: "Amount"
      right_value: 100000
    on_true:
      action: "api_call"
      endpoint: "/flag"
      payload:
        tier: "HIGH"
      next_decision:
        id: "currency_check"
        name: "Currency sub-check"
        condition:
          operator: "eq"
          left_column: "Currency"
          right_value: "USD"
        on_true:
          action: "api_call"
          endpoint: "/flag"
          payload:
            sub_tier: "HIGH_USD"
        on_false:
          action: "db_update"
          set:
            sub_tier: "HIGH_NON_USD"
    on_false:
      action: "db_update"
      set:
        tier: "LOW"
```

### 5.3 Compound Conditions

```yaml
decision_trees:
  - id: "complex_check"
    name: "Active high-value in approved region"
    condition:
      operator: "and"
      conditions:
        - operator: "eq"
          left_column: "Status"
          right_value: "Active"
        - operator: "gt"
          left_column: "Balance"
          right_value: 50000
        - operator: "or"
          conditions:
            - operator: "in"
              left_column: "Region"
              values: ["US", "EU", "UK"]
            - operator: "eq"
              left_column: "OverrideApproved"
              right_value: "Yes"
    on_true:
      action: "api_call"
      endpoint: "/priority/high"
      payload:
        flag: "PRIORITY_ACCOUNT"
    on_false:
      action: "none"
```

### 5.4 Exception Logging Pattern

```yaml
  - id: "email_check"
    name: "Missing email"
    condition:
      operator: "is_null"
      left_column: "Email"
    on_true:
      action: "api_call"
      endpoint: "/exceptions/log"
      payload:
        exception_id: 1
        exception_type: "MISSING_EMAIL"
        message: "Email field is null"
    on_false:
      action: "db_update"
      set:
        email_status: "OK"
```

The agent identifies exceptions by detecting `"exception"` in the `endpoint` string or `"exception_id"` in the `payload`. This convention-over-configuration approach avoids needing a separate exception schema.

### 5.5 Operator Quick Reference

| Operator | Category | YAML Fields | Example |
|----------|----------|-------------|---------|
| `gt` | Comparison | `left_column`, `right_column` or `right_value` | `BB > BC` |
| `gte` | Comparison | same | `Amount >= 100000` |
| `lt` | Comparison | same | `Score < 50` |
| `lte` | Comparison | same | `Age <= 65` |
| `eq` | Comparison | same | `Status == "Active"` |
| `neq` | Comparison | same | `Type != "INVALID"` |
| `contains` | String | `left_column`, `right_value` | `"URGENT" in Description` |
| `starts_with` | String | same | `Ref starts with "TXN-"` |
| `ends_with` | String | same | `Email ends with "@co.uk"` |
| `regex` | String | `left_column`, `pattern` | `Ref matches ^TXN-[A-Z]{3}-\d{6}$` |
| `is_empty` | String | `left_column` | `Name is blank` |
| `is_null` | Null | `left_column` | `Email is null/NaN` |
| `is_not_null` | Null | `left_column` | `Phone exists` |
| `between` | Range | `left_column`, `low`, `high` | `0 <= Score <= 100` |
| `in` | Set | `left_column`, `values` | `Country in [US, UK, CA]` |
| `not_in` | Set | `left_column`, `values` | `Type not in [X, Y, Z]` |
| `and` | Compound | `conditions` (list) | All conditions must be true |
| `or` | Compound | `conditions` (list) | At least one must be true |

---

## 6. Output Data Structures

### 6.1 dt:decisions (Full Tree Traversal)

```json
[
  {
    "node_id": "amount_tier",
    "node_name": "Amount classification",
    "result": true,
    "branch": "on_true",
    "action": {
      "action": "api_call",
      "endpoint": "/flag",
      "method": "POST",
      "payload": {"tier": "HIGH"}
    },
    "children": [
      {
        "node_id": "currency_check",
        "node_name": "Currency sub-check",
        "result": false,
        "branch": "on_false",
        "action": {
          "action": "db_update",
          "set": {"sub_tier": "HIGH_NON_USD"}
        },
        "children": []
      }
    ]
  }
]
```

### 6.2 dt:actions (Flat Action List)

```json
[
  {
    "node_id": "amount_tier",
    "node_name": "Amount classification",
    "result": true,
    "branch": "on_true",
    "action": "api_call",
    "endpoint": "/flag",
    "method": "POST",
    "payload": {"tier": "HIGH"}
  },
  {
    "node_id": "currency_check",
    "node_name": "Currency sub-check",
    "result": false,
    "branch": "on_false",
    "action": "db_update",
    "set": {"sub_tier": "HIGH_NON_USD"}
  }
]
```

### 6.3 dt:exceptions (Exception Actions Only)

```json
[
  {
    "node_id": "email_check",
    "node_name": "Missing email",
    "result": true,
    "branch": "on_true",
    "action": "api_call",
    "endpoint": "/exceptions/log",
    "payload": {
      "exception_id": 1,
      "exception_type": "MISSING_EMAIL",
      "message": "Email field is null"
    }
  }
]
```

---

## 7. Pipeline Integration Patterns

### 7.1 Single Row in a SequentialAgent

The most common pattern. A data-loading agent puts one row in state, the DecisionTreeAgent evaluates it, and a downstream agent acts on the results.

```python
from google.adk.agents import SequentialAgent

pipeline = SequentialAgent(
    name="LoanValidation",
    sub_agents=[
        DataLoaderAgent(name="Loader"),         # writes dt:row
        DecisionTreeAgent(
            name="Validator",
            config_path="config/rules.yaml",
        ),                                       # reads dt:row, writes dt:actions
        ActionExecutorAgent(name="Executor"),    # reads dt:actions, executes them
    ],
)
```

### 7.2 Row-by-Row Loop with LoopAgent

Process an Excel file row by row. The outer LoopAgent iterates, a callback sets `dt:row` from a row list each iteration, and the DecisionTreeAgent evaluates.

```python
from google.adk.agents import SequentialAgent, LoopAgent

def before_each(cb_ctx):
    """Set dt:row from the row list for each iteration."""
    rows = cb_ctx.session.state.get("all_rows", [])
    idx = cb_ctx.session.state.get("loop_index", 0)
    if idx < len(rows):
        cb_ctx.session.state["dt:row"] = rows[idx]
        cb_ctx.session.state["loop_index"] = idx + 1
    else:
        cb_ctx.session.state["loop_done"] = True

loop = LoopAgent(
    name="RowLoop",
    max_iterations=1000,
    before_agent_callback=before_each,
    sub_agents=[
        DecisionTreeAgent(name="DT", config_path="config/rules.yaml"),
        ResultCollectorAgent(name="Collector"),  # appends dt:actions to a master list
    ],
)

pipeline = SequentialAgent(
    name="BatchValidation",
    sub_agents=[
        ExcelLoaderAgent(name="Loader"),  # writes all_rows to state
        loop,
        SummaryAgent(name="Summary"),
    ],
)
```

### 7.3 Parallel Rule Sets with ParallelAgent

Run two independent rule sets against the same row simultaneously.

```python
from google.adk.agents import ParallelAgent, SequentialAgent

parallel_validation = ParallelAgent(
    name="ParallelRules",
    sub_agents=[
        DecisionTreeAgent(
            name="LoanRules",
            config_path="config/loan_rules.yaml",
            state_prefix="loan",
        ),
        DecisionTreeAgent(
            name="ComplianceRules",
            config_path="config/compliance_rules.yaml",
            state_prefix="comp",
        ),
    ],
)

# Upstream agent must set both loan:row and comp:row
# Or use a before_agent_callback to copy dt:row → loan:row and comp:row
```

### 7.4 Dynamic Config from LLM Agent

An LLM agent generates YAML rules on the fly. The DecisionTreeAgent evaluates them deterministically.

```python
pipeline = SequentialAgent(
    name="DynamicValidation",
    sub_agents=[
        RuleGeneratorAgent(name="RuleGen"),   # LLM agent that writes dt:config_yaml
        DecisionTreeAgent(name="DT"),          # reads dt:config_yaml, evaluates dt:row
        ResultAgent(name="Results"),
    ],
)
```

### 7.5 Conditional Downstream with output_key

Use `dt:passed` to conditionally route downstream processing.

```python
def check_passed(cb_ctx):
    """Skip downstream agent if all validations passed."""
    if cb_ctx.session.state.get("dt:passed", True):
        return False  # skip — no exceptions to handle
    return True  # proceed — exceptions need attention

pipeline = SequentialAgent(
    name="ConditionalPipeline",
    sub_agents=[
        DataAgent(name="Data"),
        DecisionTreeAgent(name="DT", config_path="config/rules.yaml"),
        ExceptionHandlerAgent(
            name="ExceptionHandler",
            before_agent_callback=check_passed,
        ),
    ],
)
```

---

## 8. Execution Flow Detail

```
┌─────────────────────────────────────────────────────────────┐
│                   _run_async_impl(ctx)                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. READ STATE                                              │
│     row = ctx.session.state["dt:row"]                       │
│     ┌─ if row is None → set dt:status="no_data", return    │
│     └─ if row exists → continue                             │
│                                                             │
│  2. LOAD CONFIG (priority order)                            │
│     ┌─ dt:config_yaml in state? → yaml.safe_load(string)   │
│     ├─ dt:config_path in state? → read file                │
│     ├─ self.config_path set?    → read file                │
│     └─ none found? → set dt:status="failed", return        │
│                                                             │
│     DecisionTreeConfig(**raw_yaml)                          │
│     ┌─ Pydantic validates schema                            │
│     └─ on error → set dt:status="failed", return           │
│                                                             │
│  3. EVALUATE                                                │
│     decisions = walk_all(config.decision_trees, row)        │
│                                                             │
│     For each tree in config.decision_trees:                 │
│       walk_tree(tree, row)                                  │
│         │                                                   │
│         ├─ evaluate(condition, row) → bool                  │
│         │   ├─ SimpleCondition → OPERATORS[op](left, right) │
│         │   └─ CompoundCondition → all/any(children)        │
│         │                                                   │
│         ├─ branch = on_true if result else on_false         │
│         │                                                   │
│         ├─ record = {node_id, result, branch, action, ...}  │
│         │                                                   │
│         └─ if branch.next_decision:                         │
│               child = walk_tree(next_decision, row)         │
│               record.children.append(child)                 │
│                                                             │
│  4. FLATTEN                                                 │
│     actions = collect_actions(decisions)                     │
│     → flat list of all non-"none" actions                   │
│                                                             │
│  5. FILTER EXCEPTIONS                                       │
│     exceptions = [a for a in actions                        │
│                   if "exception" in endpoint                │
│                   or "exception_id" in payload]             │
│                                                             │
│  6. WRITE STATE                                             │
│     dt:decisions  = decisions                               │
│     dt:actions    = actions                                 │
│     dt:exceptions = exceptions                              │
│     dt:passed     = (len(exceptions) == 0)                  │
│     dt:status     = "completed"                             │
│                                                             │
│  7. YIELD SUMMARY                                           │
│     Content: "Row evaluated: N actions, M exception(s)"     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. YAML-to-Evaluation Mapping

How a YAML condition becomes a Python evaluation.

```
YAML:                              Python execution:
─────                              ─────────────────
condition:                         evaluate(condition, row)
  operator: "and"                    → compound: all(...)
  conditions:                      
    - operator: "eq"                   → OPERATORS["eq"]
      left_column: "Status"                (row["Status"], "Active")
      right_value: "Active"                → True
    - operator: "gt"                   → OPERATORS["gt"]
      left_column: "Balance"               (row["Balance"], 50000)
      right_value: 50000                   → True (if Balance > 50000)
                                       → all([True, True]) → True

on_true:                           branch = on_true (because result is True)
  action: "api_call"               action_output = {
  endpoint: "/priority"                "action": "api_call",
  payload:                             "endpoint": "/priority",
    flag: "HIGH"                       "payload": {"flag": "HIGH"}
                                   }

                                   record = {
                                       "node_id": "...",
                                       "result": True,
                                       "branch": "on_true",
                                       "action": action_output,
                                       "children": []
                                   }
```

---

## 10. Error Handling Strategy

### 10.1 Errors That Halt the Agent

| Error | When | Agent Response |
|-------|------|---------------|
| No `dt:row` in state | Step 1 | Sets `dt:status = "no_data"`, yields message, returns |
| No config source found | Step 2 | Sets `dt:status = "failed"`, `dt:error` = message, returns |
| YAML parse error | Step 2 | Sets `dt:status = "failed"`, `dt:error` = exception message, returns |
| Pydantic validation error | Step 2 | Sets `dt:status = "failed"`, `dt:error` = field-level details, returns |
| Any uncaught exception | Any step | Caught by outer try/except, sets `dt:status = "failed"`, returns |

### 10.2 Errors That Do NOT Halt the Agent

| Situation | Behavior |
|-----------|----------|
| Column missing from row | `row.get(column)` returns `None`. Null-safe operators handle it gracefully. Comparison operators return `False`. |
| Type coercion failure | Falls back to string comparison. Logged at DEBUG level. |
| NaN value in row | Treated as null by `_is_null()`. All comparison operators return `False`. `is_null` returns `True`. |

### 10.3 What the Agent Never Does on Error

- It never raises an exception that propagates to the ADK runner (all exceptions are caught).
- It never writes partial results. Either all outputs are written (success) or only `dt:status` and `dt:error` are written (failure).
- It never silently swallows errors. Every error is logged and set in `dt:error`.

---

## 11. Performance Characteristics

| Dimension | Measured Value | Notes |
|-----------|---------------|-------|
| Config loading | < 5ms | One-time Pydantic validation |
| Per-tree evaluation | < 0.1ms | In-memory dict lookup and comparison |
| 5 trees × 1 row | < 1ms total | Proven in test_engine.py |
| 16 trees × 1 row | < 2ms total | LAM conversion config (nested to depth 6) |
| Memory overhead | < 1MB | Config + row + results. No batching, no accumulation. |
| LLM tokens consumed | 0 | No LLM calls. Pure deterministic evaluation. |

---

## 12. Testing

### 12.1 Test Matrix

The `test_engine.py` file validates the following scenarios.

| Row | Trees Hit | Expected Outcome |
|-----|-----------|-----------------|
| ROW-001 | BB>BC ✓, Amount≥100k ✓ → USD ✓, Email not null ✓, Active+Balance>50k ✓, Country US ✓ | Passed, 6 actions, 0 exceptions |
| ROW-002 | BB<BC ✗, Amount<100k ✗, Email null ✓ → Exception 1, Inactive ✗, Country BR ✗ → Exception 2 | Failed, 4 actions, 2 exceptions |
| ROW-003 | BB=BC ✗ (gt not gte), Amount=100k ✓ (gte) → JPY ✗, Email OK ✓, Active but Balance<50k ✗, DE ✓ | Passed, 5 actions, 0 exceptions |

### 12.2 What Each Row Tests

- **ROW-001:** Happy path. All conditions pass. Nested tree traversal reaches leaf (HIGH → USD → HIGH_USD). Verifies `gt`, `gte`, `eq`, `is_null` (false path), compound `and`, and `in` operators.
- **ROW-002:** Exception path. Two exceptions raised (MISSING_EMAIL, UNAPPROVED_COUNTRY). Verifies null handling, `not_in` detection, and exception extraction logic.
- **ROW-003:** Edge cases. `BB == BC` tests that `gt` does not match equality (only `gte` would). `Amount = 100000` tests boundary condition for `gte`. `Currency = JPY` tests the `on_false` path of a nested decision. `Balance = 30000` tests compound `and` failure when one subcondition fails.

---

## 13. Extending the Agent

### 13.1 Adding a Custom Operator

Edit `engine/evaluator.py` and add to the `OPERATORS` dict.

```python
# Add a "modulo" operator: left % right == 0
OPERATORS["divisible_by"] = lambda l, r, **_: (
    not _is_null(l) and not _is_null(r) and float(l) % float(r) == 0
)
KWARGS_ONLY_OPS.add("divisible_by")  # if it uses kwargs instead of positional right
```

Then use in YAML immediately:

```yaml
condition:
  operator: "divisible_by"
  left_column: "AccountNumber"
  right_value: 10
```

No schema changes needed. Pydantic will need the operator added to the `Literal` type in `SimpleCondition` for strict validation.

### 13.2 Adding a Custom Action Type

The current agent does not execute actions — it only records them. But if you want to add a new action type to the YAML schema, add it to the `Literal` in `ActionBranch.action`.

```python
# In models/schemas.py
action: Literal["api_call", "db_update", "log_only", "none", "slack_notify"] = "none"
```

Then in the downstream `ActionExecutorAgent`, handle `"slack_notify"` in its dispatch logic.

### 13.3 Custom State Prefix

```python
# Two agents evaluating different rule sets against different data
loan_dt = DecisionTreeAgent(name="LoanDT", state_prefix="loan", config_path="config/loan.yaml")
aml_dt = DecisionTreeAgent(name="AMLDT", state_prefix="aml", config_path="config/aml.yaml")

# State keys:
# loan:row, loan:decisions, loan:passed, loan:actions, loan:exceptions
# aml:row,  aml:decisions,  aml:passed,  aml:actions,  aml:exceptions
```

---

## 14. Decision Record

### 14.1 Why This Architecture

| Alternative Considered | Why Rejected |
|----------------------|-------------|
| LLM-based evaluation | Non-deterministic. Same row can produce different results across runs. Unacceptable for compliance. Expensive at scale. |
| Hardcoded Python rules | Zero code change principle violated. Every rule change requires code review and redeployment. |
| Database-stored rules | Adds infrastructure dependency. YAML in git gives version control, diff, and review for free. |
| JSON config instead of YAML | YAML is more readable for business analysts. Supports comments. Maps naturally to flowchart structure. |
| Batch processing inside the agent | Violates single responsibility. Batching should be handled by a `LoopAgent` or upstream orchestrator. |
| Action execution inside the agent | Violates single responsibility. The agent evaluates rules. A downstream agent executes actions. This separation enables dry-run by default. |

### 14.2 What Could Change

| Aspect | Current | Possible Evolution |
|--------|---------|-------------------|
| Config format | YAML file on disk | YAML from database, API, or LLM-generated |
| Row source | `dt:row` in state | Could support `dt:rows` (batch) with internal iteration |
| Exception detection | Convention (`"exception"` in endpoint) | Could add explicit `is_exception: true` field to ActionBranch |
| Operator registry | Static dict in evaluator.py | Could be loaded from a separate YAML file |
| DAG support | Separate DAGExecutor module | Could be integrated as a wrapping agent |
