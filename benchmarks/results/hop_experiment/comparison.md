# 2-hop experiment: results

Every trial is in every denominator. 'Bug file retrieved' is retrieval only; errored trials still have a
deterministic retrieval, but the raw records of errored trials carry no file list, so it is recomputed in the
analysis files only for completed trials: here it is reported over completed trials with n shown.

## gemma3:1b

| run | trials | valid patch (all tests pass) | target test fixed | patch produced | timeouts | HTTP errors | unusable output | bug file retrieved (completed) | mean prompt tok (completed) | median inference s |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline run (old code) · graph (1-hop) | 12 | 0/12 (0%) | 0/12 (0%) | 0/12 (0%) | 0/12 (0%) | 2/12 (17%) | 0/12 (0%) | 4/10 (40%) | 1411 | 3.15 |
| control run (current code) · graph (1-hop) | 12 | 0/12 (0%) | 1/12 (8%) | 1/12 (8%) | 0/12 (0%) | 1/12 (8%) | 0/12 (0%) | 3/11 (27%) | 1341 | 1.18 |
| experiment (current code) · graph2 (2-hop) | 12 | 0/12 (0%) | 0/12 (0%) | 0/12 (0%) | 0/12 (0%) | 1/12 (8%) | 3/12 (25%) | 9/11 (82%) | 1454 | 3.62 |

Outcome breakdown (counts of all trials):

| run | valid_patch | timeout | http_error | other_error | unusable_model_output | no_patch_proposed | patch_application_failure | patch_applies_bug_not_fixed | regression_target_fixed_others_fail |
|---|---|---|---|---|---|---|---|---|---|
| baseline run (old code) · graph (1-hop) | 0 | 0 | 2 | 0 | 0 | 10 | 0 | 0 | 0 |
| control run (current code) · graph (1-hop) | 0 | 0 | 1 | 0 | 0 | 10 | 0 | 0 | 1 |
| experiment (current code) · graph2 (2-hop) | 0 | 0 | 1 | 0 | 3 | 8 | 0 | 0 | 0 |

Per case, valid patches / trials:

| case | baseline run (old code) · graph (1-hop) | control run (current code) · graph (1-hop) | experiment (current code) · graph2 (2-hop) |
|---|---|---|---|
| free_shipping_boundary | 0/2 | 0/2 | 0/2 |
| moving_average_window | 0/2 | 0/2 | 0/2 |
| mutable_default_argument | 0/2 | 0/2 | 0/2 |
| pagination_off_by_one | 0/2 | 0/2 | 0/2 |
| price_thousands_separator | 0/2 | 0/2 | 0/2 |
| shallow_config_merge | 0/2 | 0/2 | 0/2 |

## qwen2.5:3b

| run | trials | valid patch (all tests pass) | target test fixed | patch produced | timeouts | HTTP errors | unusable output | bug file retrieved (completed) | mean prompt tok (completed) | median inference s |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline run (old code) · graph (1-hop) | 12 | 2/12 (17%) | 4/12 (33%) | 5/12 (42%) | 1/12 (8%) | 1/12 (8%) | 0/12 (0%) | 4/10 (40%) | 1188 | 3.73 |
| control run (current code) · graph (1-hop) | 12 | 2/12 (17%) | 4/12 (33%) | 4/12 (33%) | 0/12 (0%) | 0/12 (0%) | 1/12 (8%) | 4/12 (33%) | 1151 | 3.76 |
| experiment (current code) · graph2 (2-hop) | 12 | 0/12 (0%) | 0/12 (0%) | 3/12 (25%) | 0/12 (0%) | 1/12 (8%) | 3/12 (25%) | 10/11 (91%) | 1238 | 3.87 |

Outcome breakdown (counts of all trials):

| run | valid_patch | timeout | http_error | other_error | unusable_model_output | no_patch_proposed | patch_application_failure | patch_applies_bug_not_fixed | regression_target_fixed_others_fail |
|---|---|---|---|---|---|---|---|---|---|
| baseline run (old code) · graph (1-hop) | 2 | 1 | 1 | 0 | 0 | 5 | 0 | 1 | 2 |
| control run (current code) · graph (1-hop) | 2 | 0 | 0 | 0 | 1 | 7 | 0 | 0 | 2 |
| experiment (current code) · graph2 (2-hop) | 0 | 0 | 1 | 0 | 3 | 5 | 0 | 3 | 0 |

Per case, valid patches / trials:

| case | baseline run (old code) · graph (1-hop) | control run (current code) · graph (1-hop) | experiment (current code) · graph2 (2-hop) |
|---|---|---|---|
| free_shipping_boundary | 0/2 | 0/2 | 0/2 |
| moving_average_window | 1/2 | 2/2 | 0/2 |
| mutable_default_argument | 0/2 | 0/2 | 0/2 |
| pagination_off_by_one | 0/2 | 0/2 | 0/2 |
| price_thousands_separator | 1/2 | 0/2 | 0/2 |
| shallow_config_merge | 0/2 | 0/2 | 0/2 |

