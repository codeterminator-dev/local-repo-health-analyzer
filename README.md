# local-repo-health-analyzer

本项目用于本地代码仓库健康巡检与依赖拓扑分析。

- 目标：对仓库结构、依赖关系与常见风险做只读分析
- 原则：不修改业务代码，不执行写入式修复
- 协作：leader、worker、reviewer 基于同一远程仓库按分支协作
