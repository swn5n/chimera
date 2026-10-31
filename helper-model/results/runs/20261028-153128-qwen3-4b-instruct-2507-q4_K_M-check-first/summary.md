# qwen3:4b-instruct-2507-q4_K_M on the helper eval (v1.1)

2026-10-28T15:31:28-05:00 · Ollama 0.40.1 · digest `0edcdef34593` · think=unset · seed=7 · samples=1 · **experiment: check-first** (not Chimera's own request)

## Reviewer

Chimera accepts 100%, strictly valid 88%, done right 83%: caught 80% of flawed results, accepted 89% of good ones, named the main flaw 92% of the time it caught one; score in band 83%. Latency p50 1.5 s. Check written first 100%, median 445 characters.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | done | 100 | – |
| rev-02 | yes | not done | not done | 60 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-05 | yes | done | done | 100 | – |
| rev-06 | yes | not done | not done | 70 | yes |
| rev-07 | yes | not done | done | 100 | – |
| rev-08 | yes | done | done | 100 | – |
| rev-09 | yes | not done | not done | 60 | no |
| rev-10 | yes | not done | not done | 50 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | not done | 30 | – |
| rev-14 | yes | not done | not done | 60 | yes |
| rev-15 | yes | done | done | 100 | – |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | done | 100 | – |
| rev-18 | yes | done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-20 | yes | not done | not done | 40 | yes |
| rev-21 | yes | done | done | 100 | – |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-23 | yes | not done | not done | 60 | yes |
| rev-24 | yes | done | done | 100 | – |

