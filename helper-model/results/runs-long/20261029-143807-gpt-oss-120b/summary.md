# gpt-oss:120b on the helper eval (long-1)

2026-10-29T14:38:07-05:00 · Ollama 0.40.1 · digest `714d86958b6e` · think=unset · seed=7 · samples=1

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 94%: caught 100% of flawed results, accepted 88% of good ones, named the main flaw 100% of the time it caught one; score in band 81%. Latency p50 5.1 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-long-01 | yes | done | done | 100 | – |
| rev-long-02 | yes | not done | not done | 70 | yes |
| rev-long-03 | yes | not done | not done | 45 | yes |
| rev-long-04 | yes | done | not done | 85 | – |
| rev-long-05 | yes | done | done | 85 | – |
| rev-long-06 | yes | not done | not done | 68 | yes |
| rev-long-07 | yes | done | done | 92 | – |
| rev-long-08 | yes | not done | not done | 45 | yes |
| rev-long-09 | yes | done | done | 95 | – |
| rev-long-10 | yes | not done | not done | 70 | yes |
| rev-long-11 | yes | done | done | 95 | – |
| rev-long-12 | yes | not done | not done | 80 | yes |
| rev-long-13 | yes | done | done | 95 | – |
| rev-long-14 | yes | not done | not done | 78 | yes |
| rev-long-15 | yes | done | done | 95 | – |
| rev-long-16 | yes | not done | not done | 85 | yes |

