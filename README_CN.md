# promotion-assistant

多渠道产品推广，自带漏斗量化与自我调优， 默认 dry-run，合规 fail-closed。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.3-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## 设计理念

推广政策随产品和渠道变化，漏斗、选择规则和发送检查则可以保持稳定。因此，公开仓保存通用
编排逻辑，产品文案、受众和运行记录放在 PRIVATE 伴生仓。这样需要多做一些配置工作，但调整
渠道政策时不必把真实活动写进工具，也不必为每个产品复制一套代码。

向每个目的地实发前，都要核对完整文案、同意与退订状态，并取得该渠道的明确授权。
dry-run 保存预览和模拟事件供审核。模拟不能证明投递成功；提供方回执不确定时，需要先核对
再决定是否重试。这些限制会减少无人值守的便利，也让不可撤回的外联始终有明确依据。

bandit 依靠已记录的反馈学习，所以事件身份和归因与选择公式同样重要。持久化的运行及观察回执
让重试复用原决定，避免将同一条观察重复计入奖励。合成检查可以验证这套记账逻辑；账号配置、
提供方接收和真实转化仍需各自的证据。

[完整设计理念](PHILOSOPHY.md)。

## 它是什么(不是什么)

**是**：一个薄的、产品无关的编排器，用于把「已发布」的产品做多渠道推广并量化反馈， 覆盖式(群发邮件 +
多平台发帖) 与 精准式(论坛回帖 + 私信)、每日多账号养号、六层转化漏斗、以及一个会自调优的 Thompson
Sampling bandit。所有产品文案/受众/凭证都放在「独立私有 config 仓」。

**不是**：垃圾轰炸机；不是调度引擎(调度委托 `schedule-reminder`)；不是市场调研工具(那是 `market-intel`)。
不绕过任何平台 ToS，构建/测试期绝不向真实受众发送。

## 安装

```
/plugin install github:DaizeDong/promotion-assistant
```

或手动克隆：

```bash
git clone --recurse-submodules https://github.com/DaizeDong/promotion-assistant.git ~/.claude/plugins/promotion-assistant
cd ~/.claude/plugins/promotion-assistant
```

然后建一个「每产品 config 仓」(fork `companion config kit` 模板，Mode B secrets)并指向它：
`export PROMO_CONFIG_DIR=~/CodesClaude/<product>-promo-config`。

需要 Python 3.11 以上、Git，以及 `~/.pii-guard/visibility.json` 中未过期的 PRIVATE 可见性回执。
运行时由固定版本的 Guards API 核验本地回执和 Git 配置，不会调用 `gh` 或自动刷新回执。
回执缺失或过期时，请先按[伴生仓约定](guards/COMPANION.md#verifying-a-companion)完成初始化或刷新。
JSON 配置不需要额外 Python 包，YAML 配置还需 PyYAML。下面的命令从克隆后的仓库目录开始运行。
提醒功能需设置 `PROMO_REMINDER_PY`，指向已安装的 `reminder.py`；先运行
`python "$PROMO_REMINDER_PY" ensure --help` 检查接口，再用 `init` 初始化本地存储。
托管安装应使用当前运行环境的 Python 和提醒脚本，只有旧 `add` 命令的版本不兼容。

`python scripts/cli.py --config /path/to/private-companion init` 用于检查已有配置，
`--config` 要放在子命令前。创建配置骨架用 `init_config.py --out`；填好配置并在独立私有仓提交后，
`verify_config.py` 才能报告 ready。

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

`promotion-assistant` 是**带 config 的 skill**, 所有产品文案、受众、按渠道 policy 与凭证都放在一个
**独立、私有**的伴随 config 仓。完整规范见 [CONFIG.md](CONFIG.md)(字段参考：[reference/config-schema.md](skills/promotion-assistant/reference/config-schema.md))。

- **挂载(发现顺序):** `$PROMO_CONFIG_DIR`(主)→ `$PROMOTION_ASSISTANT_CONFIG` →
  `$PROMOTION_ASSISTANT_CONFIG_DIR` → `~/.promotion-assistant-config/` →
  `~/.config/promotion-assistant-config/`。显式路径或优先级最高的非空环境变量一旦选定，就必须通过校验，失败不会转用另一个产品。
  只有没有指定路径和环境变量时才查找家目录。所选目录须属于独立、有提交历史的私有伴生仓，所有 remote 的 fetch/push 目的地都须确认 PRIVATE。
- **首次配置：**
  ```bash
  cd skills/promotion-assistant
  python scripts/init_config.py        # 生成符合规范的 config 骨架(确定性)
  export PROMO_CONFIG_DIR=~/.promotion-assistant-config   # 或给 init 传 --out <dir>
  python scripts/verify_config.py       # doctor:逐项 PASS/FAIL,明确报缺什么
  ```
- **邮件设置：** helper 须实现完整的 [reviewed-email-v1 协议](skills/promotion-assistant/reference/email-helper-contract.md)，并在渠道中明确配置。
  仅有旧 helper 文件或 message ID 不足以确认发件人和完整正文；安装环境仍需单独核验。
- **切换 config(即插即用):** 把环境变量指向另一个 config 目录即可， config 自包含，无需任何别的改动：
  `export PROMO_CONFIG_DIR=~/configs/product-a` ↔ `~/configs/product-b`。
- **密钥：** Mode B, `secrets/*` 已 gitignore,永不入库；请用库外备份。凭证经 config 仓自带的
  (从 companion config kit fork 的)`scripts/apply.py` 桥接进活动配置。

## 如何触发

触发词： 推广 / promotion / 营销自动化 / 外联 / 群发邮件 / 多平台发帖 / 增长 / 漏斗 / 多账号。(或直接跑 CLI)

## 示例输出

dry-run 下 `run --once` 返回 `run_id`、`status`、`counts` 和完整的 `items`，逐个列出目的地、
完整文案、同意与退订状态、回执和能否重试。模拟结果标为 `simulated`，预览和事件写入私有伴生仓，
不会调用渠道发送接口。私有存储和恢复运行的用法见 [CONFIG.md](CONFIG.md)。

## 局限

- 开 live 是**逐渠道、需显式授权、且不在构建/测试范围内**(本阶段只 dry-run)。
- 邮件、自有服 Discord、Mastodon 和 Bluesky 已有自动发送接口；已登记的人工渠道使用 `prep`，
  X 和未知平台暂不支持自动发送。自动发送仍需逐渠道授权，并取得匹配的远端回执。
  `channels list --json` 分别列出实现情况、本地配置和实发证据；合成测试不算实发证据。
- 平台 ToS 灰区无法消除；节流/拟人层只降低、不消除封号概率。

## 语言

中文 (`README_CN.md`) · English (`README.md`, 权威版)

## Roadmap · 贡献 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE)(MIT)。
