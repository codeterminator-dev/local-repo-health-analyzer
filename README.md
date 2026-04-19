# local-repo-health-analyzer

本项目用于对本地代码仓库执行只读健康巡检，输出结构质量、依赖拓扑与常见风险信号，帮助开发团队在不修改业务代码的前提下快速了解仓库状态。

## 项目目标

- 扫描仓库结构，识别体量、模块边界与目录异常
- 分析依赖关系，构建跨模块依赖拓扑
- 汇总仓库健康信号，例如孤立模块、循环依赖、过大目录与可疑资产
- 生成可读报告，供 leader、worker、reviewer 协作使用

## 当前状态

当前仓库处于协作基础设施初始化阶段，优先完善文档、分支规范与 PR 流程，为后续功能开发提供统一约束。

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/codeterminator-dev/local-repo-health-analyzer.git
cd local-repo-health-analyzer
```

### 2. 阅读协作文档

- 先阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)
- 所有功能开发都应从 `main` 创建主题分支
- 禁止直接向 `main` 推送，统一通过 Pull Request 合并

### 3. 创建工作分支

支持的分支命名约定如下：

- `feature/<short-topic>`: 新功能或能力扩展
- `bugfix/<short-topic>`: 缺陷修复
- `infrastructure/<short-topic>`: 仓库基础设施、CI、文档和工程治理

示例：

```bash
git checkout -b feature/dependency-graph
```

### 4. 提交并发起 PR

```bash
git add .
git commit -m "feat: add dependency graph analyzer"
git push origin feature/dependency-graph
```

随后在 GitHub 上向 `main` 发起 Pull Request，并按模板补充变更背景、验证结果与风险说明。

## 架构概览

当前代码尚未实现，建议后续按以下职责拆分目录：

```text
.
├── analyzer/        # 健康检查核心逻辑
├── collectors/      # 仓库结构、文件、依赖信息采集
├── reporters/       # Markdown/JSON/CLI 报告生成
├── rules/           # 可扩展的巡检规则定义
├── tests/           # 单元测试与集成测试
└── .github/         # 协作模板与 GitHub 仓库配置
```

建议模块职责如下：

- `collectors`: 负责读取仓库元数据与目录内容，不执行写入操作
- `analyzer`: 负责聚合采集结果并输出健康指标
- `rules`: 负责定义和注册单项巡检规则
- `reporters`: 负责把分析结果渲染为开发者可消费的输出

## 协作方式

- `main` 为受保护分支，只接受经过评审的 Pull Request
- PR 应保持聚焦，单次变更尽量只解决一个明确问题
- 每个 PR 都必须写明验证方式，方便 reviewer 在新容器中复现

## License

本项目使用 [MIT License](./LICENSE)。
