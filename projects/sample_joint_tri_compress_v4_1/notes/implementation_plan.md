# Implementation Plan

## MVP path
- 先实现统一预算器
- 再接 weight / activation / KV 三端轻量决策
- 先不做大规模 QAT

## Risks
- 如果收益主要来自某一端压缩，需降级主张
