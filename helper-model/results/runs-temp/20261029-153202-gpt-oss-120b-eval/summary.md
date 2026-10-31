# gpt-oss:120b on the helper eval (v1.1)

2026-10-29T15:32:02-05:00 · Ollama 0.40.1 · digest `714d86958b6e` · think=unset · seed=none · samples=10

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 93%: caught 93% of flawed results, accepted 92% of good ones, named the main flaw 99% of the time it caught one; score in band 94%. Latency p50 3.5 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | done | 95 | – |
| rev-01 | yes | done | done | 95 | – |
| rev-01 | yes | done | done | 90 | – |
| rev-01 | yes | done | done | 95 | – |
| rev-01 | yes | done | done | 95 | – |
| rev-01 | yes | done | done | 90 | – |
| rev-01 | yes | done | done | 95 | – |
| rev-01 | yes | done | done | 100 | – |
| rev-01 | yes | done | done | 95 | – |
| rev-01 | yes | done | done | 95 | – |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-02 | yes | not done | not done | 80 | yes |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-02 | yes | not done | not done | 80 | yes |
| rev-02 | yes | not done | not done | 70 | yes |
| rev-03 | yes | not done | not done | 30 | yes |
| rev-03 | yes | not done | not done | 30 | yes |
| rev-03 | yes | not done | not done | 35 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 30 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-03 | yes | not done | not done | 30 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-04 | yes | not done | not done | 68 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-04 | yes | not done | not done | 60 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-04 | yes | not done | not done | 60 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 92 | – |
| rev-05 | yes | done | done | 93 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-05 | yes | done | done | 90 | – |
| rev-05 | yes | done | done | 92 | – |
| rev-05 | yes | done | done | 85 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-06 | yes | not done | not done | 30 | yes |
| rev-06 | yes | not done | not done | 0 | no |
| rev-06 | yes | not done | not done | 30 | yes |
| rev-06 | yes | not done | not done | 30 | yes |
| rev-06 | yes | not done | not done | 48 | yes |
| rev-06 | yes | not done | not done | 38 | yes |
| rev-06 | yes | not done | not done | 35 | yes |
| rev-06 | yes | not done | not done | 38 | yes |
| rev-06 | yes | not done | not done | 40 | yes |
| rev-06 | yes | not done | not done | 30 | yes |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 92 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 100 | – |
| rev-07 | yes | not done | done | 100 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 96 | – |
| rev-08 | yes | done | not done | 78 | – |
| rev-08 | yes | done | not done | 85 | – |
| rev-08 | yes | done | not done | 85 | – |
| rev-08 | yes | done | not done | 85 | – |
| rev-08 | yes | done | done | 95 | – |
| rev-08 | yes | done | done | 95 | – |
| rev-08 | yes | done | not done | 85 | – |
| rev-08 | yes | done | done | 90 | – |
| rev-08 | yes | done | not done | 85 | – |
| rev-08 | yes | done | not done | 85 | – |
| rev-09 | yes | not done | not done | 70 | yes |
| rev-09 | yes | not done | not done | 60 | yes |
| rev-09 | yes | not done | not done | 60 | yes |
| rev-09 | yes | not done | not done | 40 | yes |
| rev-09 | yes | not done | not done | 60 | yes |
| rev-09 | yes | not done | not done | 60 | yes |
| rev-09 | yes | not done | not done | 40 | yes |
| rev-09 | yes | not done | not done | 55 | yes |
| rev-09 | yes | not done | not done | 60 | yes |
| rev-09 | yes | not done | not done | 40 | yes |
| rev-10 | yes | not done | not done | 40 | yes |
| rev-10 | yes | not done | not done | 45 | yes |
| rev-10 | yes | not done | not done | 40 | yes |
| rev-10 | yes | not done | not done | 42 | yes |
| rev-10 | yes | not done | not done | 45 | yes |
| rev-10 | yes | not done | not done | 42 | yes |
| rev-10 | yes | not done | not done | 40 | yes |
| rev-10 | yes | not done | not done | 60 | yes |
| rev-10 | yes | not done | not done | 40 | yes |
| rev-10 | yes | not done | not done | 45 | yes |
| rev-11 | yes | not done | not done | 10 | yes |
| rev-11 | yes | not done | not done | 10 | yes |
| rev-11 | yes | not done | not done | 10 | yes |
| rev-11 | yes | not done | not done | 12 | yes |
| rev-11 | yes | not done | not done | 12 | yes |
| rev-11 | yes | not done | not done | 12 | yes |
| rev-11 | yes | not done | not done | 15 | yes |
| rev-11 | yes | not done | not done | 10 | yes |
| rev-11 | yes | not done | not done | 10 | yes |
| rev-11 | yes | not done | not done | 12 | yes |
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
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 95 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-14 | yes | not done | not done | 60 | yes |
| rev-14 | yes | not done | not done | 70 | yes |
| rev-14 | yes | not done | not done | 60 | yes |
| rev-14 | yes | not done | not done | 30 | yes |
| rev-14 | yes | not done | not done | 55 | yes |
| rev-14 | yes | not done | not done | 60 | yes |
| rev-14 | yes | not done | not done | 30 | yes |
| rev-14 | yes | not done | not done | 45 | yes |
| rev-14 | yes | not done | not done | 60 | yes |
| rev-14 | yes | not done | not done | 60 | yes |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 95 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 100 | – |
| rev-15 | yes | done | done | 95 | – |
| rev-16 | yes | not done | not done | 40 | yes |
| rev-16 | yes | not done | not done | 55 | yes |
| rev-16 | yes | not done | not done | 50 | yes |
| rev-16 | yes | not done | not done | 40 | yes |
| rev-16 | yes | not done | not done | 40 | yes |
| rev-16 | yes | not done | not done | 55 | yes |
| rev-16 | yes | not done | not done | 40 | yes |
| rev-16 | yes | not done | not done | 40 | yes |
| rev-16 | yes | not done | not done | 40 | yes |
| rev-16 | yes | not done | not done | 45 | yes |
| rev-17 | yes | not done | not done | 20 | yes |
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
| rev-19 | yes | not done | not done | 75 | yes |
| rev-19 | yes | not done | not done | 75 | yes |
| rev-19 | yes | not done | not done | 75 | yes |
| rev-19 | yes | not done | not done | 75 | yes |
| rev-19 | yes | not done | not done | 70 | yes |
| rev-19 | yes | not done | not done | 75 | yes |
| rev-19 | yes | not done | not done | 75 | yes |
| rev-19 | yes | not done | not done | 70 | yes |
| rev-19 | yes | not done | not done | 75 | yes |
| rev-19 | yes | not done | not done | 75 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 20 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 30 | yes |
| rev-20 | yes | not done | not done | 20 | yes |
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
| rev-21 | yes | done | done | 100 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 95 | – |
| rev-21 | yes | done | done | 100 | – |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 15 | yes |
| rev-22 | yes | not done | not done | 10 | yes |
| rev-22 | yes | not done | not done | 5 | yes |
| rev-23 | yes | not done | not done | 60 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 45 | yes |
| rev-23 | yes | not done | not done | 60 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 60 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 70 | yes |
| rev-23 | yes | not done | not done | 60 | yes |
| rev-23 | yes | not done | not done | 60 | yes |
| rev-24 | yes | done | done | 100 | – |
| rev-24 | yes | done | done | 100 | – |
| rev-24 | yes | done | done | 95 | – |
| rev-24 | yes | done | done | 100 | – |
| rev-24 | yes | done | done | 100 | – |
| rev-24 | yes | done | done | 95 | – |
| rev-24 | yes | done | done | 100 | – |
| rev-24 | yes | done | done | 95 | – |
| rev-24 | yes | done | done | 95 | – |
| rev-24 | yes | done | done | 95 | – |

