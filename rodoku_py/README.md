# Rodoku（Python / PyTorch / 方案A后端）本地跑通指南

本目录的目标：让你在 **Windows 本地**完成“安装 PyTorch → 验证可运行 → 跑一个最小 FastAPI 服务（方案A）”的全流程闭环。

---

## 1) 创建虚拟环境（推荐）

在仓库根目录运行：

```powershell
python -m venv rodoku_py\.venv
rodoku_py\.venv\Scripts\python -m pip install --upgrade pip
```

---

## 2) 安装依赖（先 CPU 版，必通）

### 2.1 安装 PyTorch（CPU）

```powershell
rodoku_py\.venv\Scripts\python -m pip install -r rodoku_py\requirements-cpu.txt
```

### 2.2 安装服务依赖

```powershell
rodoku_py\.venv\Scripts\python -m pip install -r rodoku_py\requirements.txt
```

---

## 3) 验证 PyTorch 是否可用

```powershell
rodoku_py\.venv\Scripts\python rodoku_py\verify_torch.py
```

你应看到：
- torch 版本号
- `cuda_available`（CPU 版应为 False）
- 一个张量运算输出

---

## 4) 启动方案A后端服务（FastAPI）

```powershell
rodoku_py\.venv\Scripts\python -m uvicorn rodoku_api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir rodoku_api
```

说明：
- **务必使用 `--reload-dir rodoku_api`**，否则 uvicorn 会监控整个仓库目录；Rodoku 在运行时会持续写入 metrics/techlib/replay/ckpt 等文件，从而触发热重载，导致 `solve_job` 内存态丢失，前端出现 `job not_found`。
- 若你不需要热重载（更稳定）：去掉 `--reload` 即可。

检查健康：
- 浏览器访问：`http://127.0.0.1:8000/health`

接口文档（Swagger）：
- `http://127.0.0.1:8000/docs`

单题求解（POST /solve）：
- body 示例：
  - `{"puzzle":"000539002009000000400001809190080003000163290200905100001350984300090600980014007","max_steps":500}`

---

## 5) 下一步（接入真正的 Rodoku 推理/训练）

当前 API 先提供骨架与 torch 可运行性证明；后续会把：
- 本地题库解析
- 推理步骤日志格式（与前端回放一致）
- forcing（短链）与秩逻辑证据
- 训练循环（云端GPU）

逐步接入 `rodoku_api`。

---

## 6) 批量刷题（本地题库 → JSON 输出）

```powershell
rodoku_py\.venv\Scripts\python -m rodoku_api.batch_solve --input path\to\bank.txt --output out\runs --limit 100 --max-steps 500
```

输出：
- `out\runs\run-00001.json` ... 每题一份（含 steps + snapshots）
- `out\runs\summary.json` ... 统计

