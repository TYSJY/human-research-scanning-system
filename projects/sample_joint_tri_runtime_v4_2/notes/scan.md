# Literature Scan

## 最近最接近的 3 类工作
1. weight-only / WA 压缩
2. KV cache 压缩
3. 分离式 pipeline 组合

## 观察
- 现有工作多数把 weight / activation / KV 分开处理。
- 很少显式把三者放在统一资源预算目标下联动优化。
