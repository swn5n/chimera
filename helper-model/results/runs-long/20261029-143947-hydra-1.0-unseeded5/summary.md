# hydra:1.0 on the helper eval (long-1)

2026-10-29T14:39:47-05:00 · Ollama 0.40.1 · digest `e7e96a78f43d` · think=unset · seed=none · samples=5

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 84%: caught 78% of flawed results, accepted 90% of good ones, named the main flaw 87% of the time it caught one; score in band 75%. Latency p50 1.2 s. Check written first 100%, median 345 characters.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-long-01 | yes | done | done | 95 | – |
| rev-long-01 | yes | done | done | 95 | – |
| rev-long-01 | yes | done | done | 100 | – |
| rev-long-01 | yes | done | done | 95 | – |
| rev-long-01 | yes | done | done | 95 | – |
| rev-long-02 | yes | not done | not done | 70 | yes |
| rev-long-02 | yes | not done | not done | 70 | yes |
| rev-long-02 | yes | not done | not done | 80 | yes |
| rev-long-02 | yes | not done | not done | 72 | yes |
| rev-long-02 | yes | not done | not done | 70 | yes |
| rev-long-03 | yes | not done | done | 100 | – |
| rev-long-03 | yes | not done | not done | 85 | no |
| rev-long-03 | yes | not done | done | 95 | – |
| rev-long-03 | yes | not done | done | 95 | – |
| rev-long-03 | yes | not done | done | 100 | – |
| rev-long-04 | yes | done | done | 95 | – |
| rev-long-04 | yes | done | done | 95 | – |
| rev-long-04 | yes | done | done | 100 | – |
| rev-long-04 | yes | done | done | 95 | – |
| rev-long-04 | yes | done | done | 95 | – |
| rev-long-05 | yes | done | not done | 80 | – |
| rev-long-05 | yes | done | not done | 75 | – |
| rev-long-05 | yes | done | done | 92 | – |
| rev-long-05 | yes | done | done | 95 | – |
| rev-long-05 | yes | done | not done | 70 | – |
| rev-long-06 | yes | not done | not done | 60 | yes |
| rev-long-06 | yes | not done | not done | 75 | no |
| rev-long-06 | yes | not done | not done | 70 | yes |
| rev-long-06 | yes | not done | not done | 50 | yes |
| rev-long-06 | yes | not done | not done | 70 | yes |
| rev-long-07 | yes | done | done | 95 | – |
| rev-long-07 | yes | done | done | 95 | – |
| rev-long-07 | yes | done | done | 95 | – |
| rev-long-07 | yes | done | done | 100 | – |
| rev-long-07 | yes | done | done | 100 | – |
| rev-long-08 | yes | not done | not done | 70 | yes |
| rev-long-08 | yes | not done | not done | 70 | yes |
| rev-long-08 | yes | not done | not done | 40 | yes |
| rev-long-08 | yes | not done | not done | 40 | yes |
| rev-long-08 | yes | not done | not done | 60 | yes |
| rev-long-09 | yes | done | done | 92 | – |
| rev-long-09 | yes | done | done | 100 | – |
| rev-long-09 | yes | done | done | 95 | – |
| rev-long-09 | yes | done | done | 95 | – |
| rev-long-09 | yes | done | not done | 78 | – |
| rev-long-10 | yes | not done | not done | 60 | yes |
| rev-long-10 | yes | not done | not done | 40 | yes |
| rev-long-10 | yes | not done | not done | 30 | yes |
| rev-long-10 | yes | not done | not done | 30 | yes |
| rev-long-10 | yes | not done | not done | 50 | yes |
| rev-long-11 | yes | done | done | 100 | – |
| rev-long-11 | yes | done | done | 95 | – |
| rev-long-11 | yes | done | done | 100 | – |
| rev-long-11 | yes | done | done | 98 | – |
| rev-long-11 | yes | done | done | 100 | – |
| rev-long-12 | yes | not done | not done | 85 | yes |
| rev-long-12 | yes | not done | not done | 85 | yes |
| rev-long-12 | yes | not done | not done | 70 | yes |
| rev-long-12 | yes | not done | not done | 80 | yes |
| rev-long-12 | yes | not done | not done | 85 | yes |
| rev-long-13 | yes | done | done | 95 | – |
| rev-long-13 | yes | done | done | 95 | – |
| rev-long-13 | yes | done | done | 90 | – |
| rev-long-13 | yes | done | done | 95 | – |
| rev-long-13 | yes | done | done | 95 | – |
| rev-long-14 | yes | not done | done | 92 | – |
| rev-long-14 | yes | not done | not done | 75 | yes |
| rev-long-14 | yes | not done | not done | 70 | yes |
| rev-long-14 | yes | not done | not done | 85 | yes |
| rev-long-14 | yes | not done | done | 95 | – |
| rev-long-15 | yes | done | done | 95 | – |
| rev-long-15 | yes | done | done | 100 | – |
| rev-long-15 | yes | done | done | 95 | – |
| rev-long-15 | yes | done | done | 95 | – |
| rev-long-15 | yes | done | done | 95 | – |
| rev-long-16 | yes | not done | done | 100 | – |
| rev-long-16 | yes | not done | not done | 85 | no |
| rev-long-16 | yes | not done | not done | 85 | no |
| rev-long-16 | yes | not done | done | 95 | – |
| rev-long-16 | yes | not done | done | 95 | – |

