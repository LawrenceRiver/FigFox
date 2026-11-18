# FigFox skill / FigFox 技能版

The portable skill lives in [skills/figfox](../skills/figfox/SKILL.md). It uses the calling assistant for reconstruction, paired inspection and repair planning, and local scripts for SVG validation, rendering and scoped native edits. It does not wrap the repository's paid-provider runner or require a separate model service.

技能版由当前助手进行重建、成对观察和局部编辑规划，本地工具执行 SVG 检查、渲染与受限原生编辑；它不是 API runner 的包装器。

## Install / 安装

```bash
npx skills@latest add LawrenceRiver/FigFox --skill figfox
```

Use `-a codex` to select Codex, or `-g` for a user-wide installation when desired. The installed directory is self-contained: SKILL.md, references, scripts, agents metadata and requirements travel together. It does not need this repository's `src/` beside it. For local scripts, use Python 3.10+ and install `requirements.txt` from the installed skill directory if Pillow is absent. Rendering uses an available `rsvg-convert`, or optional CairoSVG. Model/API credentials and SAM are not prerequisites for skill mode.

可按需加 `-a codex` 或 `-g`。安装目录自包含，工具不依赖仓库旁边的 `src/`；本地工具使用 Python 3.10+ 与 Pillow，渲染使用可用的 rsvg-convert 或可选 CairoSVG。无需模型 API 凭据或 SAM。

## Workflow / 流程

```text
Source figure / 原图
  → complete native SVG draft / 完整原生 SVG 初稿
  → rendered source/draft inspection / 实际渲染的成对检查
  → verified observations + scoped transactions / 核实观察与局部事务
  → local edits + rerender / 本地编辑与重新渲染
  → actual editability probe / 实际编辑验证
  → final.svg + final.png + evidence / 可编辑文件、预览与记录
```

Text, notation, diagrams and connectors are native SVG elements. Photos may remain independent embedded source crops. Never treat a source-image wrapper or panel screenshots as editable reconstruction. Preserve source-visible errors unless correction is requested; uncertain literals stay uncertain. Report same-assistant role passes honestly rather than calling them independent reviewers. The portable operation interface supports set/text/remove/append_svg/replace_svg/source_crop; TP, SAM and API services remain optional repository capabilities outside this installed helper.

文字、公式、图形和连线保持原生可编辑，照片可作为独立内嵌裁图；不能用整图或整片文字截图冒充重建。未获纠错要求时保留原图可见内容，不猜测看不清的标签；同一助手顺序检查不宣称独立审稿。

## Companion generation Skill / 配套生成 Skill

[FigFox-Gen repository / 生成 Skill 仓库](https://github.com/LawrenceRiver/FigFox-Gen-skill) · [Skill source / 技能入口](https://github.com/LawrenceRiver/FigFox-Gen-skill/blob/main/SKILL.md)

FigFox-Gen creates a new scientific figure PNG from Methodology, with optional visual references. Install it separately:

FigFox-Gen 从 Methodology 生成新的科研图 PNG，可提供视觉参考；它需要单独安装：

```bash
npx skills@latest add LawrenceRiver/FigFox-Gen-skill --skill FigFox-Gen-skill
```

Invoke `$FigFox-Gen-skill` with your Methodology. After selecting its PNG output, explicitly invoke `$figfox` to reconstruct it as editable SVG. The generation Skill does not itself promise SVG output. See its [installation requirements](https://github.com/LawrenceRiver/FigFox-Gen-skill#installation) and [examples](https://github.com/LawrenceRiver/FigFox-Gen-skill#examples).

先用 `$FigFox-Gen-skill` 生成 PNG，再选定图片并明确调用 `$figfox` 重建 SVG。生成 Skill 本身不交付可编辑 SVG，两步分别调用。

## Output and limits / 输出与限制

FigFox reconstructs a supplied figure as editable SVG and renders a PNG preview. Text, diagrams and connectors can be native SVG elements; photos may remain separate embedded crops. Compare the render with the source and verify any edits. Unclear source labels should not be guessed, and checks by the same assistant should not be described as independent human review.

FigFox 根据原图重建可编辑 SVG，并渲染 PNG 预览。文字、图形和连线可使用原生 SVG 元素，照片可保留为独立内嵌裁图。应对照原图检查渲染结果并验证局部修改；看不清的文字不要猜测，同一助手的复核不应称为独立人工审稿。
