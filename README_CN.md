# promotion-assistant

规划多渠道产品推广，逐个审核投递目的地，用 Thompson Sampling bandit 分析漏斗反馈。发送默认使用 dry-run。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#语言)
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

## 适用范围

本工具编排已发布产品的推广，包括群发邮件、多平台发帖、论坛回复和私信准备，提供账号活动规划、
六层转化漏斗，以及根据已有反馈选择策略的 Thompson Sampling bandit。产品文案、受众和凭据
保存在独立的 PRIVATE 伴生仓中。

调度交给 `schedule-reminder`，市场与竞品研究使用 `market-intel`。构建和测试不向真实受众发送。
获得授权的实际推广仍须遵守平台条款和对应渠道要求。

## 安装

```
/plugin install github:DaizeDong/promotion-assistant
```

或手动克隆：

```bash
git clone --recurse-submodules https://github.com/DaizeDong/promotion-assistant.git ~/.claude/plugins/promotion-assistant
cd ~/.claude/plugins/promotion-assistant
```

需要 Python 3.11 以上和 Git。JSON 配置不需要额外 Python 包，YAML 还需 PyYAML。
运行快速开始前，先按下面的配置步骤建立独立的 PRIVATE 伴生仓。运行时核验
`~/.pii-guard/visibility.json` 中的本地 PRIVATE 回执，不会调用 `gh` 或刷新缺失、过期的证据。
证明流程见[伴生仓约定](guards/COMPANION.md#verifying-a-companion)。

活动规划还需要兼容的 `schedule-reminder`。按[集成设置](skills/promotion-assistant/reference/integration.md#schedule-reminder-the-only-scheduling-surface)
选择 `PROMO_REMINDER_PY`，检查 `creation-preflight`、`ensure`，并用当前运行环境的 Python
初始化存储。只有旧 `add` 命令的版本不兼容。

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

建立独立、有提交历史的 PRIVATE 伴生仓，并将 `PROMO_CONFIG_DIR` 指向它。
[CONFIG.md](CONFIG.md)规定完整发现顺序、字段、凭据键和切换步骤；[DATA.md](DATA.md)规定保留和恢复。

从仓库根运行：

```bash
python skills/promotion-assistant/scripts/init_config.py --out <private-companion>
python skills/promotion-assistant/scripts/verify_config.py --config-dir <private-companion>
```

骨架还需要填写 product/registry 的 `schema_version: 1`、产品名称和渠道 slug/platform，并完成
PRIVATE fetch/push 证明及选定提供方的资源配置。初始化结束不代表就绪。初始化器仍生成旧凭据排除
规则；将必需的 `secrets/*.env` 纳入版本管理前，先执行[仅限伴生仓的修正步骤](CONFIG.md#first-time-setup-e3)。
提供方映射从所选目录的 `secrets/runtime.env` 读取，格式为 `KEY=VALUE`。

切换前清除优先级更高的旧变量，再运行 doctor。`init` 检查已有配置，全局 `--config` 必须放在
子命令前；`apply` 执行本地 doctor，不运行历史伴生仓 helper，也不修改 `~/.claude.json`。
READY 只验证结构、PRIVATE 和本地资源。实际投递还须通过独立的进程级
`PROMO_LIVE_AUTHORIZED_<CHANNEL>` 授权并取得提供方回执；邮件另需 `reviewed-email-v1` helper。

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
- 平台条款和账号限制仍然适用。节流/拟人层用于限制活动风险，但不能据此认定平台已认可活动，
  也不能认定封号概率已经通过测量降低。

## 语言

中文 (`README_CN.md`) · English (`README.md`, 权威版)

## Roadmap · 贡献 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE)(MIT)。
