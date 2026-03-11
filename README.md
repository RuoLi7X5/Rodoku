# Rodoku — 数独秩推理 + 神经网络研究

> 只研究 **9×9 标准数独**。
>
> 本项目以 **Truth / Link / Rank** 秩结构为核心驱动删数推理，并在此基础上引入神经网络训练流水线，探索"唯一性感知（UR Sensor）"与"策略运行时（Policy Runtime）"对求解质量的提升。

---

## 技术架构

```
前端（React + Vite + TypeScript）
  └── RodokuPage   盘面交互、候选标注、秩结构查询与可视化
  └── VizPage      训练/求解可视化大盘

后端（Python + FastAPI）
  └── solver_core      核心求解引擎（规则推理 + Referee 裁判）
  └── rank_engine      秩结构搜索（Truth/Link/Rank）
  └── nn_models        神经网络模型定义（UR Sensor 等）
  └── nn_state         盘面状态 → 张量转换
  └── policy_runtime   UR Sensor 推理接口（evaluate_ur）
  └── learn_params     强化学习超参数管理
  └── train_jobs       训练任务调度
  └── solve_jobs       异步求解任务
  └── replay_store     经验回放存储
  └── puzzle_bank      题库管理
  └── techlib_store    技法库存储
  └── metrics_store    训练指标持久化
  └── log_store        日志存储
```

---

## 快速启动

### 前端

```bash
npm install
npm run dev
```

### 后端

```bash
pip install fastapi uvicorn torch numpy
uvicorn rodoku_api.main:app --reload --port 8765
```

---

## 已实现能力

### 盘面与交互

- 行/列/宫合法性校验；提示数不可编辑
- 候选数以 **3×3** 布局显示在格子内
- `forbidden` 持久删候选：被删候选不会被"全标/刷新"加回
- 填入数字后自动对同行/同列/同宫排除候选

### 题目导入（兼容多格式）

| 格式 | 说明 |
|------|------|
| 81格字符串 | `0` / `.` / 空格 均视为空格 |
| 特殊格式 | `:...:题面:用户填数:删数::` |

- 导入后自动全标候选并前端秒解
- **无解**拒绝导入；**多解**允许导入并提示；**唯一解**用于导航

### 秩结构查询与可视化

- Truth 数量范围默认 1–8，支持查询 / Stop 中断
- 仅计算 **R < 3（R=0/1/2）** 的结构
- 可视化：Truth 粗实线 + 圈选覆盖候选；Link 虚线；删数红色实心圈
- 列表按顺序编号，同删数自动去重；点击"应用"即落盘并隐藏失效项

### 神经网络 & 训练（第一阶段）

- **UR Sensor**：评估当前盘面唯一性安全评分（0.0 危险 → 1.0 安全）
- **Policy Runtime**（`evaluate_ur`）：嵌入求解器 UR Safety Check，防止推理陷入多解陷阱
- **训练流水线**：异步训练任务 + 经验回放 + 超参热更新 + 指标持久化
- **UR Generator**（`ur_generator.py`）：构造 UR 样本用于模型训练
- **VizPage 大盘**：实时呈现训练曲线与求解状态

---

## 目录结构

```
Rank-Sudoku/
├── src/
│   ├── rodoku/         前端盘面页
│   └── viz/            训练可视化页
├── rodoku_api/         Python 后端
│   ├── solver_core.py
│   ├── rank_engine.py
│   ├── nn_models.py
│   ├── nn_state.py
│   ├── policy_runtime.py
│   ├── train_jobs.py
│   ├── solve_jobs.py
│   ├── replay_store.py
│   ├── ur_generator.py
│   └── ...
├── data/               运行时数据（题库、模型权重、回放）
├── start_training.py   一键启动训练脚本
└── vite.config.ts
```

---

## 开发计划

- [ ] UR Sensor 精度提升与更大规模训练
- [ ] 将 Policy Runtime 扩展至更多推理技法（XY-Wing、鱼形等）
- [ ] 秩结构搜索性能优化（剪枝策略）
- [ ] 多盘面并行训练支持
