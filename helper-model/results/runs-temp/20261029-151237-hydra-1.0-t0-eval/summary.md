# hydra:1.0 on the helper eval (v1.1)

2026-10-29T15:12:37-05:00 · Ollama 0.40.1 · digest `e7e96a78f43d` · think=unset · seed=none · samples=10 · temperature=0

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 75%: caught 87% of flawed results, accepted 56% of good ones, named the main flaw 92% of the time it caught one; score in band 79%. Latency p50 1.1 s. Check written first 100%, median 261 characters.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-01 | yes | done | not done | 85 | – |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-02 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-04 | yes | not done | not done | 80 | yes |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-08 | yes | done | not done | 40 | – |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-09 | yes | not done | not done | 80 | yes |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-10 | yes | not done | not done | 40 | no |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-13 | yes | done | not done | 70 | – |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-14 | yes | not done | not done | 40 | yes |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 30 | yes |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |
| rev-24 | yes | done | not done | 40 | – |

