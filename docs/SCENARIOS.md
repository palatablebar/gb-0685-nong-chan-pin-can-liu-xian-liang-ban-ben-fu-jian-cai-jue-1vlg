# 检测场景

12个苹果样本分4批，每个样本初检P01为<0.01mg/kg，采样日标准限量0.005，因此不确定。次日同样本同方法复检0.004且LOD0.001，判为PASS并替代原报告。每样本P02为30ug/kg，超过0.02mg/kg，仍FAIL。最终24项目，12PASS、12FAIL，四批均FAIL。脏批额外含缺LOD、同版冲突、错列、空行与重复表头。

## 补录拆批（sample_data/supplement.csv）

S003原属B001，补录把该样本改入B002：P01以00037（version 3、报告日2026-08-04、relation指向00008）重报，P02以00038随样本迁移。

- 归属台账裁决为“补录改批”：原归属B001不变记录，裁定批次B002，原报告00007/行11可追溯。
- B001变为2样本4项，B002变为4样本8项，业务总数仍24项，12PASS/12FAIL不变。旧B001的3行标记“被替代”，仍计为采纳证据并保留在封存证据中，但不参与计算与判级。
- 同一样本只出一个结论：按原归属会得出B001三样本、按补录归属会得出B001两样本加B002四样本；后者才是拆批更正的真实结果。若两条补录分别主张B002与B004，则判为“归属冲突”，保留B001原判级并隔离两条主张，临近出证的旧批次不被翻转。
- 同一补录重复提交（相同id/version/内容）只按重复计数一次；相同id/version内容不同则整次修订返回409，原批次结果保持可读、可复核。

复现：

```bash
python -c "from app.workflow import run,load;from pathlib import Path;s=run(load('clean.csv'),{'supplements':[Path('sample_data/supplement.csv').read_text()]});print(s['attribution']['summary'],s['reconcile']['grades'])"
```
