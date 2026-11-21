# 科研数据产品目录与项目资格开通工作台

面向医学研究中心的数据治理系统：在正式开通前回答三个问题——**能用哪些字段**（产品字段 × 用途条件 × 成员范围 × 伦理约束求交）、**字段在所需时间范围内是否可用**（字段可用期 ∩ 资格有效期）、**计算额度是否适配**（预算 / 并发占用 / 实际消耗账本），并对每一次数据访问可还原当时的产品定义、资格依据与额度变化。

在此之上建立**各中心数据产品刷新时效画像与就绪判定**：记录中心-产品分区的预期交付窗、批次生成/接收/校验时间、修订标记与失败原因，计算实际延迟分布、连续未更新区间、迟到补传比例与按研究时间窗的数据水位；就绪判定器把「项目 × 产品 × 分析截止日」映射为及时/延迟/缺失/待校验/预期无采集状态，**只判定与展示水位，不替中心补造数据**。

- 后端：FastAPI + SQLAlchemy + PostgreSQL（Swagger UI 自带）
- 前端：Vue 3 + Vite + Element Plus
- 全部业务数据均为**虚构演示数据**，首次启动自动注入

## 快速开始

### 方式一：Docker Compose 一键启动（推荐）

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端工作台 | http://localhost:8080 |
| 后端 API / Swagger UI | http://localhost:8000/docs |
| PostgreSQL | localhost:5432（ccdev/ccdev） |

后端启动时自动建表；空库自动注入种子数据（幂等，重复启动不重复插入）。

### 方式二：本地开发

前置：Python 3.12、Node 22、PostgreSQL（库/用户/密码 `ccdev`）。

```bash
# 后端（终端 1）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# 若清华镜像 403，改用 -i https://mirrors.aliyun.com/pypi/simple/
.venv/bin/uvicorn app.main:app --reload --port 8000

# 前端（终端 2）
cd frontend
npm install        # 已配置 npmmirror 源
npm run dev        # http://localhost:5173 ，/api 自动代理到 8000
```

连接其他数据库：`DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname .venv/bin/uvicorn app.main:app`

### 测试账号

| 账号 | 密码 | 角色 | 说明 |
| --- | --- | --- | --- |
| admin | admin123 | 数据治理管理员 | 目录维护、批次开通、伦理失效/恢复、全部查询 |
| wangjianguo | wang123 | 课题负责人（PI） | PRJ-A 负责人，可开通批次、查询/导出 |
| zhangmin | zhang123 | 数据分析师 | **同时是 PRJ-A 与 PRJ-B 成员**（跨课题边界演示） |
| zhaolei | zhao123 | 数据分析师 | PRJ-A 统计师角色（仅查询、不可导出） |
| auditor | audit123 | 审计员 | 访问依据回查 |

## 核心设计：资格模型取舍

题目给出两种授权模式，本系统**实现「独立资格实例」模式**，理由与适用边界如下：

| 维度 | 独立资格实例（本系统） | 项目级资格包 |
| --- | --- | --- |
| 记录数 | 每个（项目×产品×用途）一条，关系多时记录多 | 每项目一条，记录少 |
| 审计 | 实例自带投影快照与依据，回查直观 | 需重放求交才能还原当时字段 |
| 撤回传播 | 只撤单个实例，影响面明确；但关系多时撤回批量大 | 一次撤回整包，传播范围大、需重算 |
| 查询路径 | 访问时按三元组直接命中投影，O(1) 绑定 | 每次访问需指定用途并现场求交，计算更重 |
| 适用场景 | 关系数量可控、查询频繁、变更（撤回/伦理失效）需精确定位 | 关系极多、查询少、变更以整包为单位 |

**两种模式共有的不变量（本系统强制）**：一次访问只绑定**一个用途**，可用字段 = 该用途求交结果，**绝不对同一成员的多个用途、多个课题取并集扩权**。成员张敏同时在 PRJ-A（TRAIN，L3）与 PRJ-B（EXTRACT，L3）任职：她以 PRJ-B 身份访问时只能命中 PRJ-B 的实例；在 PRJ-A 内用窄用途 PUBLISH（L2）访问时，也不会并入 TRAIN 的 L3 字段。

### 资格编译器求交规则（`backend/app/services/compiler.py`）

- 敏感等级上限 = min（伦理批件上限， 用途条件上限）
- 禁用标签 = 伦理禁用 ∪ 用途禁用（直接标识符 / 准标识符 / 遗传信息）
- 字段有效窗口 = 字段可用期 ∩ 资格有效期；资格有效期 = min（伦理有效期止， 课题结题日）
- 成员范围 = 签发时在职且在任期内的成员（快照进实例）
- 伦理批件失效 / 用途未申报 / 无在职成员 / 投影为空 → 拒绝签发

### 批次处理与伦理失效

开通批次逐项编译，**每项实时重查伦理状态**：处理中失效的项标记「签发失败」并记录原因，已完成项保持「已签发」独立状态；批次状态只能是 完成 / 部分完成 / 失败，**绝不整体假报成功**。

### 额度账本

- 并发占用：账户行级 `SELECT ... FOR UPDATE` 串行化「检查 + 占用」，占用数绝不超过上限（有多线程测试佐证）
- 幂等扣减：用量事件以 `idempotency_key` 全局唯一，断线重试重复上报**只扣一次**，每次上报（含重复）都留痕，重复回执可按键回查
- 访问请求级幂等：`request_id` 唯一，重试返回同一访问事件，不重复扣额度

### 审计回查

每次访问把**当时的产品定义（含目录版本）、资格依据（伦理批件/用途条件/成员范围快照）、额度变化（占用、回执、扣减后余额）**整体快照进访问事件；回查时与当前目录逐字段对比（等级/标签/窗口/增删差异），目录后续变更不影响历史快照。

## 刷新时效画像与就绪判定

### 数据模型（`backend/app/models.py`，服务在 `services/refresh.py`）

| 表 | 作用 |
| --- | --- |
| `research_centers` | 研究中心与周内排程（ISO 周一=1…周日=7；不含周末即周末停采） |
| `refresh_contracts` | （中心 × 产品）刷新合约：频率（每日/每周/每月）、交付窗天数、截止时刻、统计分位与最少历史批次 |
| `collection_pauses` | 计划停诊/停采窗口（可中心整体或单产品），窗口内标记「预期无采集」而非迟交 |
| `refresh_events` | 刷新事件：分区数据日、批次号、事件性质、生成/接收/校验时间、质控失败原因、版次、被更正事件、预期截止与两类延迟 |
| `readiness_snapshots` | 就绪判定快照：冻结实际水位、分区级判定原因与引用事件 id，新批次只标记 superseded 不覆盖 |

刷新事件的三种性质与四种状态：

- 性质：`全量刷新` / `迟到补传`（历史分区补交付）/ `更正发布`（修订旧分区，**不是全量刷新**，须指向被更正批次）。
- 状态：`已接收`（质控未完成）/ `已校验`（可用）/ `校验失败`（文件到达但**不进水位**）/ `已更正`（旧批次被修订替代）。

### 关键规则（题目约束逐条落地）

1. **文件到达 ≠ 可用数据**：质控失败/待校验批次不进入数据水位，对应就绪状态为「待校验」并附失败原因；补传批次通过质控后才承担该分区水位。
2. **首次发布延迟与更正延迟分离**：首次发布延迟 = 最早可用批次接收时间 − 预期截止；更正延迟 = 更正批次接收时间 − 被更正批次接收时间，更正不改变首次发布事实，更新文件不会被当作全量刷新。
3. **计划停诊不算迟交**：停诊窗口内的预期分区判「预期无采集」并注明原因；周末不在排程内，根本不会被枚举为预期分区。
4. **画像指标可由事件复算**：首次发布延迟分位数（min/P50/P90/max/均值）、连续未更新区间（含停诊日标注）、迟到补传比例、更正延迟分布、研究窗数据水位（可用分区、最新可用分区/时间、记录数、待校验/失败/更正分区清单）。
5. **增量影响范围**：新批次只把引用了该（中心 × 产品 × 分区）且研究截止范围覆盖它的旧快照标记 `superseded`；**旧快照冻结的水位与原因保持不变**，可随时用引用事件复算对照。

### 两种判定模式的取舍（本系统两者都实现，评估时可选）

| 维度 | 固定期限 `fixed`（目录约定） | 统计阈值 `statistical`（历史到达分布） |
| --- | --- | --- |
| 阈值来源 | 合约 `expected_window_days` + 截止时刻，逾期即延迟 | 历史已校验首次发布批次的延迟 p 分位（默认 p90）条件时效区间 |
| 优点 | 直观、可直接向中心追责 | 能识别周末/节假日规律与中心排程差异 |
| 局限 | 对有规律的停诊与不同中心排程不够贴合 | 需要足够历史批次（默认 ≥8），阈值解释更复杂 |
| 降级 | — | 历史不足时自动回退固定期限，并在分区依据中写明回退原因 |

两种模式回答同一个问题：**该数据产品能否满足分析截止要求**。判定结果始终同时给出总体状态、分区级原因与**实际水位**，而不是只有红黄颜色。状态严重度：待校验/缺失 > 延迟 > 及时/预期无采集，总体取研究窗内最严重分区。

### 种子场景（虚构数据，位于 `seed.py::_seed_refresh`）

- RC-01 城东中心：P-LAB/P-IMG **按日**交付、周末停采；含一次**质控失败后迟到补传**、一次**历史更正**、一次迟交 3 天的全量刷新、一个**待校验**批次与 3 天**计划停采**。
- RC-02 西城中心：P-FU **按周**交付（每周一分区，8 周历史，含 1 次迟交）。
- RC-03 南郊分院：P-LAB 在 10 个工作日前**长期断更**（连续缺口），P-BIO **按月**交付；另有 2 天中心整体停诊。

## 验证方式

### 自动化验收（已实际执行通过）

```bash
cd backend
.venv/bin/python -m pytest tests/ -q     # 22 passed（独立测试库 ccdev_test，不影响演示数据）
```

覆盖题目要求的全部验收点：

| 模块 | 验收点 | 用例 |
| --- | --- | --- |
| 资格/额度/审计（原有） | 字段交集、资格边界、伦理失效批次、并发占用、幂等、审计回查 | `test_acceptance.py`（11 个） |
| 刷新时效 | 延迟分位数/补传比例/更正延迟可由事件复算 | `test_seed_profile_metrics` |
| 刷新时效 | 固定期限 vs 统计阈值结论差异、历史不足回退固定 | `test_fixed_vs_statistical_mode`、`test_statistical_falls_back_to_fixed_when_history_insufficient` |
| 刷新时效 | 质控失败不进水位、补传通过后才可用且按补传计首次延迟 | `test_qc_failed_not_usable_until_backfill` |
| 刷新时效 | 更正与首次发布延迟分离、更正不是全量刷新、版次替代 | `test_correction_separates_publish_and_correction_delay` |
| 刷新时效 | 周末停采/计划停诊 → 预期无采集而非迟交 | `test_weekend_and_pause_are_not_late` |
| 刷新时效 | 长期无新批次的连续缺口、水位与缺失判定 | `test_long_gap_and_watermark` |
| 刷新时效 | 周/月产品按周期枚举分区（不把非排程日当缺失） | `test_weekly_and_monthly_partition_enumeration` |
| 刷新时效 | 快照冻结、增量 superseded 范围、事件复算对照 | `test_snapshot_frozen_superseded_and_recompute` |
| 刷新时效 | 登记约束（重复全量/无历史补传/权限）与水位出参结构 | `test_register_guards`、`test_readiness_reason_and_watermark_shape` |

### 手工 UI 验收路径

1. **产品目录**：admin 登录 → 产品目录 → 点开「检验指标数据产品」→ 查看字段语义/敏感等级/可用时间范围 → 编辑 `test_result` 为 L4 → 目录版本 v1→v2，变更日志留痕。
2. **资格开通**：资格开通工作台 → 新建批次：加三项（PRJ-A×P-FU×TRAIN、PRJ-C×P-LAB×REVIEW、PRJ-C×P-IMG×REVIEW）→ 提交 → 批次「部分完成」：PRJ-A 项已签发，PRJ-C 两项「签发失败（伦理失效）」。点实例「详情」看字段投影与资格依据。
3. **资格边界**：zhangmin 登录 → 数据访问模拟 → 选 PRJ-B / P-LAB / TRAIN → 拒绝「无已签发资格」；改选 PRJ-B / P-IMG / EXTRACT → 成功，仅 7 个非 L4 字段；再选 PRJ-A / P-LAB / PUBLISH → 仅 5 个低敏字段（不并入 TRAIN 的 L3 字段）。
4. **并发额度**：额度账本 → 对 PRJ-B（上限 2）连点 3 次「占用一个槽位」→ 第 3 次提示已达上限 → 释放一个后可再占用。
5. **重复事件**：额度账本 → 上报用量（机时 2.5，记下幂等键）→ 点「同一键再报一次」→ 提示重复未扣减 → 回执查询输入该键 → 可见 1 首次 + 1 重复回执，账户只扣 2.5。
6. **访问依据回查**：auditor 登录 → 审计查询 → 点任一成功事件 → 还原当时产品定义、伦理批件依据、额度回执；第 1 步改过字段后，此处「当时 vs 现在」出现 L3→L4 差异。
7. **刷新时效画像**：任意角色登录 → 刷新时效画像 → 选 RC-01 × P-LAB：可见首次发布延迟分位数（最大 64h 来自质控失败后的迟到补传）、迟到补传比例、独立的更正延迟（126.33h）、统计模式 p90 阈值与连续缺口；切到 RC-03 × P-LAB 可见 11-18 日后的长期断更缺口。
8. **就绪判定**：同一页右侧选课题 PRJ-A、研究窗与分析截止日：
   - 固定期限对 RC-01 × P-LAB 截止到今天 → 总体「待校验」（昨日批次已接收未质控），分区级原因写明失败/待校验；
   - 切到统计阈值，对「截止前 1 小时到达」类批次会给出与固定期限不同的延迟结论；历史不足的中心自动回退固定期限并注明；
   - 水位区显示可用分区数、最新可用分区、记录数、待校验/失败/更正分区清单（实际水位而非只有状态）。
9. **质控与补传（admin）**：刷新事件页对待校验批次点「失败」登记原因 → 该分区从水位移除、就绪变「待校验」；再登记「迟到补传」并质控通过 → 分区恢复可用且首次发布延迟按补传时间计算；登记「更正发布」指向旧批次 → 旧批次变「已更正」，版次升为 2，更正延迟单独统计。
10. **停诊与快照复算**：停诊窗口页登记设备保养区间 → 覆盖该日的就绪判定显示「预期无采集」；历史快照页对任一快照点「复算」，对照冻结水位与当前复算结论；在快照引用分区内登记新批次后，该快照标记「已过时」但冻结内容不变。

## API 概览

Swagger UI：`/docs`（OpenAPI 3.1）。主要端点：

- `POST /api/auth/login` 登录；`GET /api/auth/me`
- `GET /api/catalog/products`、`GET /api/catalog/products/{id}`、`PUT /api/catalog/products/{id}/fields/{fid}`（目录变更留痕）、`GET /api/catalog/products/{id}/changes`
- `GET /api/projects`、`GET /api/projects/{id}`、`POST /api/projects/{id}/ethics/{eid}/revoke|restore`
- `POST /api/qualifications/batches`（批次开通）、`GET /api/qualifications[/…]`、`POST /api/qualifications/{id}/revoke`
- `POST /api/access/query`（数据访问，request_id 幂等）、`GET /api/access/events`
- `GET /api/quota/accounts`、`POST /api/quota/reservations[/{id}/release]`、`POST /api/quota/usage`（幂等键）、`GET /api/quota/usage/by-key/{key}/receipts`
- `GET /api/audit/access/{id}`（访问依据回查，ADMIN/AUDITOR）
- 刷新时效（`/api/refresh`，Swagger 可见完整 schema）：
  - `GET/POST /centers`、`GET/POST /contracts`、`GET/POST /pauses`
  - `GET/POST /events`、`POST /events/{id}/qc-pass|qc-fail`（事件登记/质控，ADMIN）
  - `GET /profiles`（时效画像：延迟分位、缺口、补传比例、统计阈值）
  - `POST /readiness`（就绪判定并冻结快照）、`GET /readiness[/{id}]`、`POST /readiness/{id}/recompute`（事件复算对照）

## 目录结构

```
backend/
  app/
    main.py            # 应用入口（lifespan 建表 + 空库自动播种）
    models.py          # 目录/课题/伦理/资格实例/批次/额度/访问事件 + 中心/合约/停诊/刷新事件/就绪快照
    services/compiler.py  # 资格编译器（求交）
    services/quota.py     # 并发占用（行锁）+ 幂等扣减
    services/refresh.py   # 刷新事件登记/质控/更正、时效画像、水位、固定/统计就绪判定与复算
    routers/           # auth/catalog/projects/qualifications/access/quota/audit/refresh
    seed.py            # 虚构演示数据（含按日/按周/每月中心、停诊、QC失败补传、更正、长期断更场景）
  tests/test_acceptance.py  # 11 个资格/额度/审计验收用例
  tests/test_refresh.py     # 11 个刷新时效与就绪判定验收用例
frontend/
  src/views/           # 目录/课题/开通工作台/访问/额度/刷新时效/审计/登录
docker-compose.yml     # db + backend + frontend 一键启动
```

## 说明与限制

- 本容器内无 Docker 守护进程，Compose 配置未在本机实际构建；后端（uvicorn 启动 + pytest 22 用例全部通过 + OpenAPI 10 个刷新端点发布）与前端（vite build 通过）已在容器内以预装运行时实际验证通过。
- 刷新事件时间使用应用服务器时区的 naive datetime；就绪评估的 `as_of` 默认取评估时刻，复算时可显式传入。
- 认证为演示级 HMAC 令牌，口令 PBKDF2 散列；生产使用需替换 `SECRET_KEY` 并接入正式身份体系。
- 数据库 `ccdev` 账号仅供本隔离环境开发测试，非生产配置。
- 系统只记录与判定中心实际交付的批次，**不替任何中心补造数据**；缺失/失败分区在水位与就绪原因中如实暴露。
