# CodeRAG 的 Codex 配置与使用说明

## 1. 目标

这份文档不是讲抽象概念，而是告诉你如何把 Codex 配置成适合当前仓库重构的工作方式。

目标有两个：

- 让 Codex 更稳定地理解这个仓库
- 让你能用较少的提示词，驱动较高质量的重构工作


## 2. 这次我为你准备了什么

我已经在仓库里新增了一个项目专用 skill 模板：

- [`codex_setup/skills/coderag-refactor/SKILL.md`](/home/zyh-ub/PyRepos/CodeRAG/codex_setup/skills/coderag-refactor/SKILL.md:1)

这个 skill 的作用是让 Codex 在处理 CodeRAG 时默认遵循这些约束：

- 把“通用代码分析平台”当成新目标，而不是继续沿用红队知识库思路
- 改代码时优先做渐进迁移，而不是粗暴全量替换
- 不再继续扩散 `MitreAttack*` 这类核心命名
- 大任务时优先按阶段拆分
- 多 agent 协作时按目录和职责切分


## 3. 为什么要用 skill

你可以把 skill 理解为“给 Codex 的项目专用操作手册”。

它和普通聊天指令的差别在于：

- 聊天指令是一次性的
- skill 是可复用的
- skill 可以把这个仓库的目标、禁忌、工作顺序固化下来

对你这种“大规模持续重构”的任务，skill 很有价值，因为你不需要每次都重新解释：

- 这个仓库之前是干什么的
- 现在要往哪里迁移
- 哪些旧逻辑是包袱
- 哪些改法是高风险的


## 4. 如何安装这个 skill

当前文件已经在仓库里生成。最稳妥的做法是把它安装到你的用户级 skill 目录：

- `~/.codex/skills/`

### 方法 A：手动复制

在终端里执行：

```bash
mkdir -p ~/.codex/skills/coderag-refactor
cp /home/zyh-ub/PyRepos/CodeRAG/codex_setup/skills/coderag-refactor/SKILL.md ~/.codex/skills/coderag-refactor/SKILL.md
```

这样以后在任何会话里，只要任务内容明显和 CodeRAG 重构相关，Codex 就更容易自动触发这个 skill。

### 方法 B：保留在仓库里，按需参考

如果你暂时不想装到全局，也可以先把它当作仓库文档来用。你在提问时直接说：

`请按 coderag-refactor skill 的约束处理`

或者：

`先读取 codex_setup/skills/coderag-refactor/SKILL.md，再开始改造`

这样也能起到接近的效果。


## 5. 如何触发 skill

最直接的方法有两种。

### 方式 1：显式触发

你在提问时直接写：

```text
使用 coderag-refactor skill，分析 upload_code 链路的重构方案
```

或者：

```text
按 coderag-refactor skill，重构 retrieval_service，目标是去红队化
```

### 方式 2：隐式触发

如果你把 skill 安装到 `~/.codex/skills/`，并且任务内容明显是：

- CodeRAG 仓库
- 红队知识库去耦
- 通用代码分析平台重构

Codex 有机会自动触发。

但对重要任务，我更建议显式写出 skill 名称，稳定性更高。


## 6. 推荐的 Codex 行为配置

对于你现在这个项目，我建议固定成下面的工作方式。

### 配置 1：单主控，分阶段执行

推荐你默认这样用：

- 1 个主 agent
- 不急着开很多子 agent
- 每次只推进一个阶段

适用原因：

- 你的项目耦合较深
- 很多模块跨目录关联
- 早期开太多 agent，容易重复劳动或改出冲突

### 配置 2：提示词固定成三段

以后你给 Codex 下任务，尽量固定成这三个部分：

1. 任务目标
2. 约束条件
3. 输出要求

例如：

```text
使用 coderag-refactor skill。
目标：把 red_kbs_analyzer 的输出模型改成通用项目分析模型。
约束：先分析影响面；不要改 retrieval；不要引入新的安全领域命名；直接改代码并验证。
输出：给出修改结果、风险点、未验证部分。
```

这种写法比“你帮我改一下这个模块”稳定很多。

### 配置 3：大任务必须分轮次

不要让 Codex 一轮里同时做：

- 改 schema
- 改分析器
- 改检索
- 改 API
- 补测试

推荐拆法：

1. 第 1 轮：只分析和列迁移清单
2. 第 2 轮：只改模型和 schema
3. 第 3 轮：只改分析链路
4. 第 4 轮：只改检索和问答
5. 第 5 轮：只补测试和文档

这是你后续提升质量最有效的配置，不是模型参数，而是任务颗粒度。


## 7. 多 Agent 推荐配置

当你已经有明确阶段，才建议开多 agent。

### 推荐分工

- 主 agent：负责总控、评审、整合结果
- Agent A：分析或修改 `red_kbs_analyzer/`
- Agent B：分析或修改 `service/`、`routes/`、`database_helper/`
- Agent C：处理 schema、迁移脚本、文档
- Agent D：补测试或做回归检查

### 使用原则

- 只有任务边界清楚时才开子 agent
- 子 agent 的写入文件不要重叠
- 主 agent 负责最终合并和复核

### 什么时候不该开多 agent

以下情况建议只用主 agent：

- 你自己还没想清楚目标
- 需要先探索整体架构
- 需要改同一个核心文件很多次
- 需要频繁迭代设计方案


## 8. 多 Agent 实操模板

下面是你后续可以直接复用的提问方式。

### 模板 1：先分析，不改代码

```text
使用 coderag-refactor skill。
先不要改代码。分析 red_kbs_analyzer、service、database_helper 三部分里所有红队耦合点。
输出：按目录列出耦合点、风险、建议迁移顺序。
```

### 模板 2：单模块改造

```text
使用 coderag-refactor skill。
目标：把 red_kbs_analyzer 的输出模型去红队化。
约束：只改 red_kbs_analyzer 和相关模型；不要碰 retrieval；优先增量迁移；修改后做最小验证。
```

### 模板 3：明确要求多 agent

```text
使用 coderag-refactor skill，并使用多 agent。
主 agent 负责总控。
Agent A 只分析 red_kbs_analyzer 的通用化改造点，不改代码。
Agent B 只分析 service 和 database_helper 的存储耦合点，不改代码。
等分析完成后，再由主 agent 汇总并提出下一步改造方案。
```

### 模板 4：并行改造

```text
使用 coderag-refactor skill，并使用多 agent。
Worker 1 负责 red_kbs_analyzer/models 和 core 的通用输出模型迁移。
Worker 2 负责新增通用 schema 文档和迁移说明。
两个 worker 不要修改同一文件。
主 agent 最后整合、检查风险并汇报验证结果。
```


## 9. 你现在最值得安装的 skill

结合你这个项目，我建议优先级如下。

### 第一优先级：仓库专用 skill

就是这次新建的：

- `coderag-refactor`

原因：

- 它最贴合当前任务
- 可以持续复用
- 可以把你的重构方向固化下来

### 第二优先级：`plugin-creator`

当你准备把“安全分析能力”从主链路中剥离为插件时，用它来搭插件骨架很合适。

### 第三优先级：`skill-creator`

后续如果你想继续扩展新的项目专用 skill，比如：

- `coderag-schema-migration`
- `coderag-retrieval-redesign`
- `coderag-test-hardening`

就可以基于它继续做。


## 10. 我建议你固定下来的协作规则

以后你和 Codex 协作，建议尽量固定这几条。

### 规则 1

先分析，再修改，再验证。

### 规则 2

一次只推进一个阶段，不要让任务目标混在一起。

### 规则 3

涉及跨目录大改时，优先让 Codex 先写方案文档。

### 规则 4

让 Codex 明确说出：

- 改了哪些文件
- 哪些地方没验证
- 哪些地方仍然保留旧逻辑

### 规则 5

多 agent 只在任务边界清楚时使用。


## 11. 你需要了解的几个核心概念

为了让你更熟练使用 Codex，下面几个概念值得先建立起来。

### skill

项目专用行为说明书。适合长期任务。

### 主 agent

当前和你对话、负责整体推进的 agent。

### 子 agent

被主 agent 派出去做局部任务的执行体。适合并行分析或分块修改。

### explorer

偏“读代码、回答问题”，适合做仓库探索。

### worker

偏“改代码、交付结果”，适合执行具体变更。


## 12. 下一步最推荐的配置动作

你现在最值得先做的是这两步：

1. 把 `coderag-refactor` 安装到 `~/.codex/skills/`
2. 以后每次大改都在提示里显式写 `使用 coderag-refactor skill`

如果你这样做，Codex 的稳定性会明显比“直接随手提需求”更高。


## 13. 下一阶段我可以继续帮你做什么

如果你愿意，我下一步可以继续直接帮你补下面两样东西之一：

1. 一个“CodeRAG 多 agent 协作手册”，专门写每类任务怎么拆 agent
2. 一个“CodeRAG 重构提示词模板库”，你以后复制粘贴就能用
