# promotion-assistant — PROGRESS

> 注：stage-2 迭代会话的 summary 声称「PROGRESS.md 已追加第二轮再迭代+修复节」，但本文件此前
> 在仓内不存在（未持久化到 CodesSelf/promotion-assistant）。本文件由第二轮复验会话新建，记录
> 第二轮的修复内容（据 commit d075e89 与源码实证回填）与本次复验结论。

### 第二轮复验(promotion-assistant)

日期 2026-06-25。基线 commit d075e89（本地，未 push）。本轮为 stage-2 修复后的独立复验 + 逐项
红线实证。结论：**全部漏洞已修、Spec-v1 全符合、既有契约零破坏、新增测试全绿**。

#### 复验执行结果（全部实跑）
- `pytest tests/` → **67 passed**（stage-1 51 → stage-2 67，+9 修复守卫 +7 E22；二次复跑仍 67/0）。
- `selftest.py` 验收闸 → **12/12 pass，0 fail，0 gap**（E1–E12 契约全保留，含 E7 dry-run 零外发）。
- `check_conformance.py`（Skill Repo Spec v1）→ **20/20 passed**。
- `budget_check.py`（本 skill）→ desc 113 / cost 144 字符，1% 预算，STATUS OK。
- plugin.json：version=0.1.0（四源一致已被 conformance 校验）、keywords=9（base-9 收尾，末位 'skill'）。
- 工作树 clean；`git ls-files` 无 .sie / metrics / secrets / .env / token / .credentials 入库。

#### stage-1 审计修复 — 逐项变异杀实证（红→绿）
- **F1（low，dispatch 文档/实现漂移）**：`_authorized` 增第二因子 expected——配置声明
  `live_authorize_token` 时改 `hmac.compare_digest` 常时比对，非空但不匹配的 token 不再解锁；
  未声明则保留「存在即授权」文档化默认。变异 `compare_digest` 判定为恒真 → **1 failed**（杀）。
- **F2（low，EmailProvider live 子进程 arg-binding）**：spawn powershell 前用 `_EMAIL_RE` 校验
  单一 email 形态 + `_arg_binding_safe` 拒绝 recipient/subject/body 任一以 '-' 开头，违规
  status=error 且不启子进程。变异移除两道校验 → **3 failed**（dash-recipient / 非 email /
  dash-subject-body 全失守，杀）；合法 email 仍正常进 live 路径（spy 实证，不真发）。
- **F3（info，over-broad `*.jsonl` ignore）**：收窄为 `*.jsonl` + `!tests/**/*.jsonl` +
  `!**/reference/**/*.jsonl`。fix **load-bearing 实证**：未跟踪探针 `tests/fixtures/__probe.jsonl`
  在 fix 下 not-ignored（rc=1），去掉 negation 后 ignored（rc=0）。
  *测试质量备注*：committed fixture 因已被 git 跟踪，`git check-ignore` 恒报 not-ignored，故
  F3 守卫对「committed fixture」这条断言对该变异不敏感（弱守卫）；但 fix 本身经未跟踪探针证实有效。
- **conformance**：审计为空，无需修；复核版本/keywords 一致。

#### 本轮新增能力（E22，人工扩测造 0→1）
- `scripts/deliverability.py` = inbox-placement probe + mailbox-pool warmup →
  deliverability-driven auto-throttle（ROADMAP「Planned」明列、旧仓全盲于真实落收件箱）。
  纯 stdlib 确定性。配 `tests/test_deliverability_e22.py` 7 断言。变异
  `placement_multiplier` → const 1.0 → **5 failed**（≥4 杀，含 throttle-vs-blind 对照 + 单调 +
  双约束 bind + 确定性 + 输入闸）。advisory standalone，未改 E4 throttle 契约（向后兼容）。

#### 红线最终确认（产品(优先)安全关键）
- **promotion dry-run 0 外发**：selftest E7 「full pipeline, only simulated events, zero live
  egress」PASS；providers 非 live 走 `_not_live` 不 spawn；live 路径 NOTE 明示构建期不自动真发。
- 无 critical/high 漏洞（stage-1 即仅 2 low + 1 info，本轮全闭）。

#### 残留 / 未尽（如实）
- self-evolve loop 自产新能力净增益 = 0（结构性，与批1-6 同因）：live(tier=A) 卡 REFLECT 未达
  JUDGE；builtin 判决 3 轮 STATIC_REJECT、accepted=[]。绿 A 档 base=None + proposer 不能 author
  测试 → ACCEPT 至多 no-regression。真增益来自人工扩测，不粉饰为 loop 自迭代。
- F3 守卫对 committed-fixture 那条断言偏弱（见上）；建议后续改用未跟踪探针断言以提升变异敏感度。
- GitHub 远端双仓（public skill + private config）push deferred；远端 base-9 topics 仍以
  plugin.keywords(9) 代偿（需用户创建远端 + 授权）。
- 库级 system-prompt 预算逼近上限（库级 WARNING 90%），非本 skill 缺陷（自身 desc 113 字符）。
- mastodon/bluesky/reddit/x live provider 仍 deferred-gap（需真实 OAuth）；deliverability 为
  advisory（未喂入 live 发送链路，待渠道授权）。G1/G2 正式 harness deferred 至 skill-smith v0.2。
- 各渠道 live 授权 + 真实 postal address + 创始人一手 ICP/卖点仍 deferred（仅登录/发送/付款/
  真实部署交用户）。提交本地 commit d075e89，未 push（留待用户）。
