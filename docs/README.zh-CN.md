# FigFox

**把已有科研图重建为可编辑 SVG，再对照原图进行局部修复。**

文字、几何形状和连线保持原生 SVG；照片和纹理可保留为独立、可移动的内嵌素材。FigFox 先构建完整初稿，再成对检查原图与渲染结果，核实问题、定位对象并执行受限编辑。

## 真实案例

![论文中的两个重建与修复案例](assets/reconstruction-samples.png)

上图直接复用论文原图，展示原始图、成对检查、修复细节和可编辑结果。[原始 SVG](assets/reconstruction-samples.svg)。[更多局部修复细节](assets/semantic-targeting-details.svg)与[方法原图](assets/framework-v80.svg)也保留为 SVG；方法原图中的 DeepSeek 虚线分支是历史扩展，当前默认配置不使用它。

## 使用方式

**FigFox Skill**：提供已有科研图，调用 `$figfox` 重建可编辑 SVG；对照原图检查后，可局部修复。安装：

```bash
npx skills@latest add LawrenceRiver/FigFox --skill figfox
```

它使用当前助手和本地工具，无需单独配置模型 API 或 SAM 服务。详见[技能说明](skill.md)。API runner 的环境与命令见[英文首页](../README.md#quick-start)和[安装说明](setup.md)。

**FigFox-Gen Skill**：输入方法正文，可附参考图片，生成新的科研图 PNG。其[正式仓库](https://github.com/LawrenceRiver/FigFox-Gen-skill)提供安装要求：

```bash
npx skills@latest add LawrenceRiver/FigFox-Gen-skill --skill FigFox-Gen-skill
```

调用 `$FigFox-Gen-skill` 生成 PNG；需要可编辑 SVG 时，选定 PNG，再单独调用 `$figfox`。

## FigFoxBench 与演示

[FigFoxBench-v3](https://huggingface.co/datasets/FigFoxBench/FigFoxBench-v3) 用于科研图重建的非商业评测。数据集目前为私有，访问需维护者授权，并遵守[版权与使用声明](figfoxbench-terms.md)。详情见[数据集说明](figfoxbench.md)。演示入口见[英文首页](../README.md#video)。
