# 数据集清单

用 `scripts/benchmark.py add-dataset` 登记自己的来源和图片。每个数据集版本包含 `dataset.json`、`images/`，可按需加入 `annotations/`、`source/`。

输入图片、参考文件和压缩包保留在本地，不随此仓库发布。模型结果位于 `benchmark/runs/`，不写回输入目录。稳定样本编号与哈希用于核对每轮实际输入；改变数据时新建版本。

登记与运行步骤见 [实验工作区](../README.md)。
