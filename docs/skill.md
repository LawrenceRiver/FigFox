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

## Verification scope / 验证范围

`tests/test_skill_package.py` copies only the skill directory into a temporary installed location and verifies native inventory, scoped text edits and unchanged neighbors, rejection of out-of-scope writes, image-wrapper warnings, paired quadrants, exact embedded source crops and actual PNG rendering. A separate real architecture-SVG editing probe checks use outside the repository. These checks establish tool behavior and portability; source fidelity still requires rendered image inspection.

便携性检查覆盖独立复制安装、原生对象统计、局部编辑及邻居保留、越界拒绝、整图包装提示、成对区域、真实素材嵌入和实际渲染；另用真实架构 SVG 检查脱离仓库后的编辑流程。工具通过不等于视觉完全一致。

[Example: FigFox-Gen V2 architecture / 示例：V2 架构图](https://github.com/LawrenceRiver/FigFox-Gen-skill/tree/main/examples/v2-architecture/editable). Its source PNG, editable SVG, rendering and editing receipts are retained with known limitations, including font approximation and the source's ambiguous arrow.


### Recorded package checks / 本次打包检查

The seven new portable-package tests and four related factual-pipeline tests pass. An isolated installation also completed actual text/group/photo edits and rendering without the source repository. The broader legacy runtime suite reports 36 failures in this environment (123 passing with the new tests); the untouched baseline reports 36 failures and 116 passing, including missing browser-runtime dependencies and unavailable process-isolation behavior. This release does not claim that broader runtime suite passes.

七项新增便携性测试与四项相关流程测试通过，脱离仓库的安装实测也完成了改字、移动组和照片及渲染。旧运行器全套测试在当前环境有 36 项失败，未修改原版同样有 36 项失败，涉及浏览器运行依赖及进程隔离环境；不把这些测试宣称为通过。
