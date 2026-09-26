# Boundary

> **Context-aware sensitive-data protection at the system boundary.**

Boundary is a local data-protection prototype that evaluates structured application data before it crosses a software boundary and applies a configurable policy using detected sensitivity, composite quasi-identifier risk, destination, and purpose.

The central idea is simple:

> **Sensitive-data handling should depend on both the data and the context in which it is being used.**

Instead of applying one global rule to every sensitive field, Boundary can transform the same logical record differently for an internal system, a third-party LLM, or an analytics destination.

---

## Architecture

```text
Application / Service
        |
        | structured data
        v
+---------------------------+
|         BOUNDARY          |
|                           |
| Detection                 |
|  - Presidio               |
|  - semantic embeddings    |
|  - static field mappings  |
|                           |
| Risk assessment           |
|  - field sensitivity      |
|  - composite linkage      |
|                           |
| Context                   |
|  - destination trust      |
|  - purpose scope          |
|                           |
| Policy                    |
|  - YAML rules             |
|                           |
| Transformation            |
|  - ALLOW                  |
|  - MASK                   |
|  - REDACT                 |
|  - GENERALIZE             |
|  - REMOVE                 |
|  - BLOCK                  |
|                           |
| Explanation + audit       |
+-------------+-------------+
              |
              v
       Downstream system
