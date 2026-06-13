---
schema: agent-friendly-md/0.1
generated_by: agent-friendly-md
source_files:
  - zhcaej4.pdf
generated_at: 2026-06-12T00:00:00Z
document_slug: zhcaej4
risk_level: high
counts:
  images: 24
  tables: 12
  formulas: 7
  blocks: 128
split: false
---

# TAC5x1x 和 TAC5x1x-Q1 可编程双二阶滤波器

> **摘要**　〔由 ir/summary.seed.md 晋升〕
> 本文档介绍 TAC5x1x 系列的可编程双二阶滤波器……（200–300 字摘要）

## 目录

- [3 滤波器设计](#3-滤波器设计)

---

## 3.1 使用 PurePath™ Console 的滤波器设计　〔源 p.4-5〕

正文忠实保留原文信息密度，不压缩为摘要。

![图 3-3. PurePath™ Console 可编程双二阶滤波器示例](assets/fig_p006_purepath_biquad_example.png)

**图 3-3. PurePath™ Console 可编程双二阶滤波器示例**　〔源 p.6〕

> **编者注**：原图 60Hz 陷波深度约 -36dB（图上估读）。

$$H(z)=\frac{b_{0}+b_{1}z^{-1}+b_{2}z^{-2}}{1+a_{1}z^{-1}+a_{2}z^{-2}}$$

*（公式 1，〔源 p.3〕）*

| 地址 | 寄存器 | 复位值 |
| --- | --- | --- |
| 0x08 | ADC_BQ1_N0_BYT1[7:0] | 0x7F |

*表 3-4. 数字双二阶滤波器系数寄存器（节选）　〔源 p.9〕*
