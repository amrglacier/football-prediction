# 全自动 AI 足球赛事分析与预测系统 V4.0

基于多因子异构委员会投票的四阶段流水线架构，具备自我进化能力。

## 快速开始

### 1. 环境准备

```bash
# 克隆项目后进入目录
cd football-prediction-system

# 复制环境配置模板
cp .env.example .env

# 编辑 .env，填入你的 API Key（至少填一个 AI Key 即可启动，未配置的因子会自动降级到 Mock）
```

### 2. Docker 一键部署（推荐）

```bash
# 构建并启动所有服务（PostgreSQL + Redis + Web + Celery Worker + Celery Beat）
docker-compose up -d --build

# 查看日志
docker-compose logs -f web
docker-compose logs -f worker
```

启动后：
- **Dashboard**: http://localhost:8000/static/index.html
- **API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/api/admin/health

### 3. 本地开发（不用 Docker）

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动 PostgreSQL 和 Redis（需本地安装或使用 docker-compose up db redis）

# 初始化数据库
python -c "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"

# 启动 Web 服务
uvicorn app.main:app --reload

# 另一个终端启动 Celery Worker
celery -A app.tasks.celery_app worker --loglevel=info

# 第三个终端启动 Celery Beat（定时调度）
celery -A app.tasks.celery_app beat --loglevel=info
```

## 免费 API 获取指南

系统设计为零成本运行。以下是各 API 的免费获取方式：

### AI 模型 API

| 因子 | 推荐模型 | 获取方式 | 免费额度 |
|------|---------|---------|---------|
| F2 | 通义千问 (Qwen) | [阿里云 DashScope](https://dashscope.console.aliyun.com/) | 新用户免费额度 |
| F3 | Kimi (Moonshot) | [Moonshot 平台](https://platform.moonshot.cn/) | 15 RPM 免费 |
| F6 | DeepSeek | [DeepSeek 平台](https://platform.deepseek.com/) | 注册送免费额度 |
| F5 | Gemini | [Google AI Studio](https://aistudio.google.com/) | 15 RPM, 1500 RPD |
| F8 | Llama 3.1 (Groq) | [Groq Console](https://console.groq.com/) | 非常慷慨的免费 tier |
| F7 | 文心一言 (ERNIE) | [百度千帆](https://qianfan.baidubce.com/) | 免费配额 |
| F1 | Claude | [Anthropic Console](https://console.anthropic.com/) | 付费（可选用 DeepSeek 替代） |
| F4 | GPT-4o | [OpenAI Platform](https://platform.openai.com/) | 付费（可选用 DeepSeek 替代） |

**最低配置**：只需配置 **DeepSeek** 或 **通义千问** 一个 API Key，系统即可运行。所有因子会自动降级到可用的 provider，未配置的因子使用 Mock 填充。

### 足球数据 API

| 提供商 | 获取方式 | 免费额度 |
|--------|---------|---------|
| API-Football | [RapidAPI](https://rapidapi.com/api-sports/api/api-football) | 100 请求/天 |

## 系统架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│  Phase 1    │     │  Phase 2    │     │  Phase 3            │     │  Phase 4        │
│  赛选层     │ ──> │  数据层     │ ──> │  多因子委员会       │ ──> │  复盘层         │
│             │     │             │     │                     │     │                 │
│ API调度     │     │ 量化官采集  │     │ 8因子并行投票       │     │ 命中统计        │
│ 规则过滤    │     │ 校验官核验  │     │ 协调员加权汇总      │     │ 偏差归因        │
│ 输出比赛清单│     │ 赔率锚定    │     │ V0/V_latest/V_hist  │     │ 因子权重迭代    │
└─────────────┘     └─────────────┘     └─────────────────────┘     └─────────────────┘
                                                                                    │
                                                                                    v
                                                                           [更新因子权重库]
```

### 8 因子委员会

| ID | 角色 | 专长 | 默认权重 |
|----|------|------|---------|
| F1 | 首席盘口师 | 赔率结构、机构意图 | 20% |
| F2 | 基本面统计 | 伤停、战意、主客场数据 | 15% |
| F3 | 战术分析师 | 阵型克制、比赛节奏 | 15% |
| F4 | 市场情绪师 | 大众心理、热度监测 | 10% |
| F5 | 历史同盘矿工 | 历史统计、概率回溯 | 10% |
| F6 | 体能周期师 | 赛程密度、疲劳指数 | 10% |
| F7 | 冷门猎手 | 意外事件、红黄牌预警 | 10% |
| F8 | 环境变量师 | 天气、草皮、裁判 | 10% |

### 封盘机制

- 工作日（周一至周五）：当日 22:00 封盘
- 周末（周六、周日）：当日 23:00 封盘
- 封盘后所有预测锁定，不再更新

### 权重自适应迭代

```
W_new = W_old * (1 - eta * Delta * I_league)
```

- eta: 学习率（默认 0.05）
- Delta: 惩罚项（错误为 1，正确为 0）
- I_league: 联赛敏感系数（北欧联赛 1.5x）

## 项目结构

```
football-prediction-system/
├── app/
│   ├── main.py                 # FastAPI 应用入口
│   ├── config.py               # 配置管理
│   ├── core/
│   │   ├── constants.py        # 常量定义（状态、因子、错误码）
│   │   ├── database.py         # 数据库引擎与会话管理
│   │   ├── state_machine.py    # 比赛状态机与封盘逻辑
│   │   └── weights.py          # 动态权重计算与迭代
│   ├── models/
│   │   └── models.py           # 10 张表 SQLAlchemy ORM
│   ├── schemas/
│   │   └── schemas.py          # Pydantic 请求/响应模型
│   ├── providers/
│   │   ├── base.py             # AI Provider 抽象层（5 种适配器）
│   │   └── registry.py         # 因子到 Provider 的映射与降级链
│   ├── prompts/
│   │   └── templates.py        # 所有 AI 角色 Prompt 模板
│   ├── services/
│   │   ├── football_api.py     # 足球数据 API 客户端
│   │   ├── phase1_selection.py # Phase 1: 赛选层
│   │   ├── phase2_data.py      # Phase 2: 数据层
│   │   ├── phase3_predict.py   # Phase 3: 预测层
│   │   └── phase4_review.py    # Phase 4: 复盘层
│   ├── tasks/
│   │   └── celery_app.py       # Celery 异步任务与调度
│   ├── api/
│   │   ├── matches.py          # 比赛相关 API
│   │   ├── monitor.py          # 监控台 API
│   │   └── admin.py            # 管理端 API
│   └── static/
│       └── index.html          # 前端 Dashboard
├── tests/
│   └── test_core.py            # 核心逻辑单元测试
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## API 接口

### 比赛相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/matches` | 比赛列表（支持筛选分页） |
| GET | `/api/matches/{id}` | 比赛详情（含预测、复盘） |
| GET | `/api/matches/{id}/predictions/history` | 预测演变时间轴 |
| GET | `/api/matches/{id}/briefing` | 核准数据简报 |
| POST | `/api/matches/{id}/trigger-prediction` | 手动触发预测 |

### 监控台

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/monitor/dashboard` | 仪表盘概览 |
| GET | `/api/monitor/factors` | 因子列表与 Provider 状态 |
| GET | `/api/monitor/weights` | 因子权重表 |
| GET | `/api/monitor/errors` | 错误日志 |
| GET | `/api/monitor/error-taxonomy` | 错误分类法 |
| GET | `/api/monitor/params` | 模型超参数 |

### 管理端

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/fetch-fixtures` | 手动拉取赛程 |
| POST | `/api/admin/matches/{id}/acquire-data` | 手动触发数据采集 |
| POST | `/api/admin/matches/{id}/predict` | 手动触发预测 |
| POST | `/api/admin/matches/{id}/review` | 手动触发复盘 |
| GET | `/api/admin/health` | 系统健康检查 |

## 使用流程

1. 配置 `.env` 文件，填入至少一个 AI API Key 和足球数据 API Key
2. `docker-compose up -d --build` 启动所有服务
3. 访问 `http://localhost:8000/api/admin/fetch-fixtures` 手动拉取赛程
4. 系统自动执行 Phase 2 → Phase 3 → 封盘 → Phase 4
5. 访问 `http://localhost:8000/static/index.html` 查看 Dashboard

## 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行单元测试
pytest tests/ -v
```

## 免责声明

本系统预测结果仅供分析参考，不构成投注建议。足球比赛具有高度不确定性，任何预测系统都无法保证准确性。请理性对待预测结果。
