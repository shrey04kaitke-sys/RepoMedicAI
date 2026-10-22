# Graph Report - shopapp  (2026-10-22)

## Corpus Check
- 9 files · ~1,842 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 113 nodes · 111 edges · 7 communities
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- notifications.py
- audit.py
- inventory.py
- reports.py
- shipping.py
- users.py
- test_cart.py

## God Nodes (most connected - your core abstractions)
1. `cart_total()` - 4 edges
2. `line_total()` - 4 edges
3. `parse_price()` - 3 edges
4. `audit_task_1()` - 2 edges
5. `audit_task_2()` - 2 edges
6. `audit_task_3()` - 2 edges
7. `audit_task_4()` - 2 edges
8. `audit_task_5()` - 2 edges
9. `audit_task_6()` - 2 edges
10. `audit_task_7()` - 2 edges

## Surprising Connections (you probably didn't know these)
- `test_cart_total_with_thousands_separator()` --calls--> `cart_total()`  [EXTRACTED]
  tests/test_cart.py → cart.py
- `cart_total()` --calls--> `line_total()`  [EXTRACTED]
  cart.py → pricing.py

## Import Cycles
- None detected.

## Communities (7 total, 0 thin omitted)

### Community 0 - "notifications.py"
Cohesion: 0.11
Nodes (8): notifications_task_1(), notifications_task_2(), notifications_task_3(), notifications_task_4(), notifications_task_5(), notifications_task_6(), notifications_task_7(), notifications_task_8()

### Community 1 - "audit.py"
Cohesion: 0.12
Nodes (8): audit_task_1(), audit_task_2(), audit_task_3(), audit_task_4(), audit_task_5(), audit_task_6(), audit_task_7(), audit_task_8()

### Community 2 - "inventory.py"
Cohesion: 0.12
Nodes (8): inventory_task_1(), inventory_task_2(), inventory_task_3(), inventory_task_4(), inventory_task_5(), inventory_task_6(), inventory_task_7(), inventory_task_8()

### Community 3 - "reports.py"
Cohesion: 0.12
Nodes (8): reports_task_1(), reports_task_2(), reports_task_3(), reports_task_4(), reports_task_5(), reports_task_6(), reports_task_7(), reports_task_8()

### Community 4 - "shipping.py"
Cohesion: 0.12
Nodes (8): shipping_task_1(), shipping_task_2(), shipping_task_3(), shipping_task_4(), shipping_task_5(), shipping_task_6(), shipping_task_7(), shipping_task_8()

### Community 5 - "users.py"
Cohesion: 0.12
Nodes (8): users_task_1(), users_task_2(), users_task_3(), users_task_4(), users_task_5(), users_task_6(), users_task_7(), users_task_8()

### Community 6 - "test_cart.py"
Cohesion: 0.31
Nodes (4): cart_total(), line_total(), parse_price(), test_cart_total_with_thousands_separator()

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Should `notifications.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1111111111111111 - nodes in this community are weakly interconnected._
- **Should `audit.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._
- **Should `inventory.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._
- **Should `reports.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._
- **Should `shipping.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._
- **Should `users.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._