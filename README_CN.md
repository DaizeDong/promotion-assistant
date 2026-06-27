# promotion-assistant

多渠道产品推广，自带漏斗量化与自我调优 —— 默认 dry-run，合规 fail-closed。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.1-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ 先读这里 — 设计理念

**方法论恒定、信号自适应；合规是工程不是自觉；dry-run 是默认而非选项。** 渠道矩阵、六层漏斗、bandit、
合规闸是固定方法；每个平台限额、受众段、文案都下沉到「每产品 config 仓」。任何真实外发都不会离开本机，
除非产品被显式置为 live **且** 该渠道被逐个授权 —— 你什么都不做时，落入的就是安全态。

📜 **[完整设计理念 -> PHILOSOPHY.md](PHILOSOPHY.md)**

---

## 它是什么(不是什么)

**是**：一个薄的、产品无关的编排器，用于把「已发布」的产品做多渠道推广并量化反馈 —— 覆盖式(群发邮件 +
多平台发帖) 与 精准式(论坛回帖 + 私信)、每日多账号养号、六层转化漏斗、以及一个会自调优的 Thompson
Sampling bandit。所有产品文案/受众/凭证都放在「独立私有 config 仓」。

**不是**：垃圾轰炸机；不是调度引擎(调度委托 `schedule-reminder`)；不是市场调研工具(那是 `market-intel`)。
不绕过任何平台 ToS，构建/测试期绝不向真实受众发送。

## 安装

```
/plugin install github:DaizeDong/promotion-assistant
```

或手动克隆:

```bash
git clone https://github.com/DaizeDong/promotion-assistant.git ~/.claude/plugins/promotion-assistant
```

然后建一个「每产品 config 仓」(fork `market-intel-config` 模板，Mode B secrets)并指向它:
`export PROMO_CONFIG_DIR=~/CodesSelf/<product>-promo-config`。

## 快速开始

```bash
cd skills/promotion-assistant
python scripts/selftest.py                          # E1-E12 验收闸(零外发)
python scripts/cli.py doctor                          # 健康 / 合规 / dry-run 状态
python scripts/cli.py plan --campaign <C>             # 内容日历 -> schedule-reminder
python scripts/cli.py run  --campaign <C> --once      # 受闸 dispatch(默认 DRY-RUN)
python scripts/cli.py report --funnel                 # 六层漏斗
```

## 配置

`promotion-assistant` 是**带 config 的 skill** —— 所有产品文案、受众、按渠道 policy 与凭证都放在一个
**独立、私有**的伴随 config 仓。完整规范见 [CONFIG.md](CONFIG.md)(字段参考:[reference/config-schema.md](skills/promotion-assistant/reference/config-schema.md))。

- **挂载(发现顺序):** `$PROMO_CONFIG_DIR`(主)→ `$PROMOTION_ASSISTANT_CONFIG` →
  `$PROMOTION_ASSISTANT_CONFIG_DIR` → `~/.promotion-assistant-config/` →
  `~/.config/promotion-assistant-config/`。命中第一个即用;都没有则 fail-closed。
- **首次配置:**
  ```bash
  cd skills/promotion-assistant
  python scripts/init_config.py        # 生成符合规范的 config 骨架(确定性)
  export PROMO_CONFIG_DIR=~/.promotion-assistant-config   # 或给 init 传 --out <dir>
  python scripts/verify_config.py       # doctor:逐项 PASS/FAIL,明确报缺什么
  ```
- **切换 config(即插即用):** 把环境变量指向另一个 config 目录即可 —— config 自包含,无需任何别的改动:
  `export PROMO_CONFIG_DIR=~/configs/product-a` ↔ `~/configs/product-b`。
- **密钥:** Mode B —— `secrets/*` 已 gitignore,永不入库;请用库外备份。凭证经 config 仓自带的
  (从 market-intel-config fork 的)`scripts/apply.py` 桥接进活动配置。

## 如何触发

触发词: 推广 / promotion / 营销自动化 / 外联 / 群发邮件 / 多平台发帖 / 增长 / 漏斗 / 多账号。(或直接跑 CLI)

## 示例输出

dry-run 下 `run --once` 打印形如 `{"status":"ok","dispatch":{"status":"simulated",...},"arm":"armA"}`，
并追加一条 `simulated` 事件 + 一行 `dry-run.jsonl` —— 在逐渠道 live 授权前，零网络外发。

## 局限

- 开 live 是**逐渠道、需显式授权、且不在构建/测试范围内**(本阶段只 dry-run)。
- 多个渠道作为 **deferred-gap** 交付(Mastodon/Bluesky/Reddit/X/PH/HN) —— 是登记而非静默丢弃；当前
  live 传输为邮件(经 `send-gmail.ps1`)与自有服 Discord，两者仍需逐渠道授权。
- 平台 ToS 灰区无法消除；节流/拟人层只降低、不消除封号概率。

## 语言

中文 (`README_CN.md`) · English (`README.md`, 权威版)

## Roadmap · 贡献 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE)(MIT)。
