# 农产品残留限量版本与复检裁决

面向农产品检测站复核员，处理采信、判定、核算、复核与归档。

## 启动

```bash
docker compose up --build -d
```

访问 http://localhost:18254 。初次启动自动运行脏样例，可切换 clean.csv 与 legacy.csv。顶部“运行批次”会重新计算，同源输入复用批次。

## 业务模块

- 报告采信：`/m1_ingest`、`/api/m1_ingest`
- 项目映射：`/m2_mapping`、`/api/m2_mapping`
- 限量选版：`/m3_versions`、`/api/m3_versions`
- 检出量换算：`/m4_segments`、`/api/m4_segments`
- 复检裁决：`/m5_calculate`、`/api/m5_calculate`
- 批次判级：`/m6_reconcile`、`/api/m6_reconcile`
- 报告归档：`/m7_archive`、`/api/m7_archive`

## 核心规则

按采样日期选择有效限量，低于检出限保留区间；复检不得越过样本关联与方法适用范围。完整数值、边界和异常定义见 `docs/DATA-DICTIONARY.md`。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

原始样例在 `sample_data/`，补录改批样例为 `sample_data/supplement.csv`。测试在 `tests/`。封存文件是单份CSV，含运行清单、修订来源、对账、逐行归属证据、计算证据与隔离原因。复核需提交当前版本，陈旧复核返回409。

## 补录与批次归属

一个样本只归属一个批次。补录以 `parameters.supplements`（CSV文本列表）提交，可同时用 `parameters.revision_of` 指向已归档批次；原批次记录不被修改，修订失败或中断时旧版仍可读、可复核。

```bash
curl -s localhost:18254/api/runs -H 'Content-Type: application/json' -d '{
  "sample":"clean.csv",
  "parameters":{"revision_of":"<原批次号>","supplements":["<补录CSV文本>"]}}'
```

- 补录改批按样本级归属裁决：批次等级、样本计数、业务项目数与归属台账同源（`reconcile.consistent`），同一样本不会同时计入两批。
- 补录行与原报告同号同版且内容一致视为重复（只计一次）；内容不同整次修订返回 `REVISION` 409。
- 并列冲突主张保留原归属并隔离主张，避免临近出证的旧批次被翻转。
- 同一基础输入与同一补录字节运行号相同，重跑不重复增删样本。
- M6 页面显示归属台账；M7 可下载 `attribution.csv` 归属台账，封存CSV含全部归属证据行。

## 数据与限制

SQLite保存在records命名卷，普通重启与构建不会清除。确认可丢弃本项目数据后，运行 `docker compose down -v` 再启动可重置。单文件上限2MB；不接入外部业务系统；历史规则由本项目样例定义，不代表实际行业标准。
