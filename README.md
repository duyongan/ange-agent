# ange-agent

> 自进化 CLI agent:**运行时自演进 × skill 代谢环 × 自建 wiki 知识引擎**。

## 设计一句话

接一条 deepseek-harness 故意断掉、hermes 没想过、llm_wiki 没做过的通路:

```
动态工具(会话内易失)──晋升──▶ 持久工具(代码轨)
                                    │退役
对话经验 ──每轮复盘(查重+高门槛)──▶ skill(SKILL.md 说明书轨)
                                    │退役
                                    ▼
                          wiki 页面("曾经这样做过"的知识)
进化失败 → 回滚上一版(每项最多保留 2 版)
```

## 技术栈

- **deepagents**(loop / planning / filesystem / SkillsMiddleware)+ LangGraph(SQLite checkpointer)
- Provider 仅 OpenAI 兼容端点(DeepSeek 默认),**不做** 39 家 profile
- CLI:`prompt_toolkit` + `rich`。**无** Chainlit / Langfuse / 沙箱 / 人审门(裸信任,已签收)

## 安装与运行

```bash
cp .env.example .env      # 填 ANGE_API_KEY(DeepSeek 或任意 OpenAI 兼容端点)
uv run ange               # 或 uv run python -m ange
```

## 命令

| 命令 | 作用 |
|---|---|
| `/skills` | 列出 skill 库 |
| `/wiki <词>` / `/wiki lint` | wiki 检索 / 一致性检查 |
| `/ingest <路径/URL>` | 两步思维链摄入(md/txt/pdf/url) |
| `/stats` | 结局信号统计(代理信号 + 复盘自评) |
| `/evolve` | 大扫除:lint 修复 + skill 退役 + 晋升工具回滚检查 |
| `/versions <tool\|skill> <name>` | 查看双版本备份 |
| `/new` / `/exit` | 新会话 / 退出 |

## 进化机制速览

- **结局信号双层**:LangGraph callback 记代理信号(工具成败);每轮结束后**异步**复盘调用让 LLM 打分 + 提议新 skill(REPL 不等待)。
- **防崩阀**:创建 skill 时查重(硬校验名字冲突 + 提示词高门槛);退役判据 = 差评率过半或 30 天未用。
- **双轨制晋升**:动态工具晋升 = Python 文件移入 `~/.ange/tools/`,下次启动 importlib 一等注册。
- **退役**:skill → wiki 墓地页(`retired/<name>`,含生平统计),目录移入 `~/.ange/retired/`。

## 数据布局(~/.ange/)

```
skills/    SKILL.md 说明书轨          wiki/    知识引擎(index.md/log.md/raw/)
tools/     晋升工具(代码轨)           retired/ 退役 skill 存放
dynamic/   会话易失动态工具            versions/ 双版本备份(回滚源)
usage.jsonl 结局信号                   sessions.db 会话持久化
```

## 明确不做(v1)

IM 适配器、Web UI、向量检索、知识图谱、多 provider、沙箱、人审门。
文档重摄入?用你已有的 llm_wiki 桌面应用,或将来自行 MCP 外呼。

## 风险

1. wiki 引擎是最大膨胀点(格式清单是闸门:md/txt/pdf/url)
2. skill 增生靠防崩阀 + 代谢环自愈,观察 `/stats`
3. 裸信任:损害窗口 = 检测延迟,回滚只救文件不救损失
4. 框架黑盒税:LangGraph 调试痛苦是"外包 loop"的已认代价
