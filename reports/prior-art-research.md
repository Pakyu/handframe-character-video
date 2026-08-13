# Prior-Art Research

- Researched at: 2026-08-11
- Queries: `gesture frame video compositing`; `mediapipe hand tracking video effects`; `video review workflow`
- Catalogs: skills.sh, SkillsMP, GitHub source, local installed skills
- Rating evidence: unavailable

统一研究器在本机遇到三个兼容性问题：默认 Python 3.10 缺少 `datetime.UTC`；Windows 子进程不能直接找到无扩展名 `npx`；一次 SkillsMP 输出受 GBK 编码影响。随后使用元技能允许的底层命令分别完成 skills.sh 与 SkillsMP 查询，并回到 GitHub 原始 `SKILL.md` 核验候选。没有执行第三方候选脚本。

| Candidate | Relevance | skills.sh installs | SkillsMP repo stars | Quality/trust evidence | Adopt | Reject | License |
|---|---|---:|---:|---|---|---|---|
| `chengfeng-videocut-skills:剪口播`（本地） | 人工审核与状态交接 | missing evidence | missing evidence | 本地完整脚本、审核服务器、状态文件与真实故障记录 | 审核前停止、实例身份、完成状态、稳定产物合同 | 不复制口误/字幕领域规则 | repository license not rechecked |
| `p-broll`（本地） | 风格预设、时长意识与逐阶段 QA | missing evidence | missing evidence | 本地完整 Skill 与参考文档 | 采用 editorial halftone 的视觉组织思路、明确预设、实际产物 QA 与时间稳定性要求 | 拒绝其付费图片/视频生成路线、生成式 3D、首尾帧生成和平台路由 | repository license not rechecked |
| `openclaw/openclaw@video-frames` | 单一视频脚本与依赖声明 | 1.1K | 385,789 | GitHub 源码；仓库持续更新 | 明确 ffmpeg 前置条件、脚本小而确定 | 不采用过窄的“只抽帧”能力边界 | GitHub API `NOASSERTION` |
| `majiayu000/claude-skill-registry@mediapipe-usage` | MediaPipe Web 运行模式 | missing evidence | 551 | MIT；GitHub 原始 Skill；链接官方 MediaPipe 文档 | VIDEO 模式、GPU/CPU、节流、平滑和清理思路 | 拒绝 `@latest`，改用固定 `0.10.14` | MIT |
| `jianshuo/claude-skills@wjs-reframing-video` | MediaPipe 视频分析与 FFmpeg 交付 | 146 | 115 | MIT；完整边界、sidecar 与零检测降级说明 | 轨迹 sidecar、源文件不变、检测失败显式降级、单次确定性渲染 | 不复制人脸/MAR/裁切算法和平台专用码率规则 | MIT |

skills.sh 安装量是生态采用数据；SkillsMP 数值是整个 GitHub 仓库 stars，二者不是评分，也没有相加。

## Public product reference

`https://www.zhuzhu.store/` 仅作为公开功能表现参考。没有在已检查主页、`app.js` 或 `live.html` 中确认开源许可证，因此没有复制其源码、文字、样式或资产。保留了“自动轨迹 + 四角校正 + 区间效果”的产品思路，检测、审核服务和渲染均独立实现。

## Contribution ledger

- `keep`：脚本化执行、源文件不变、结构化 sidecar、审核确认闸门、状态身份核验。
- `adapt`：把浏览器 Canvas 导出改为 OpenCV 逐帧处理加 FFmpeg H.264 封装；把 MediaPipe 自动检测改为固定版本 Web 主路径加人工降级；把 P-broll 的 editorial halftone 视觉语言改造成稳定、无模型费用的本地逐帧算法。
- `reject`：摄像头与实时特效；网页源码复制；未固定的 `@latest`；绕过依赖哈希；未经用户确认直接渲染；付费图片/视频生成与生成式场景重构。
- `invent`：单原片自动派生 `generated_inside.mp4`、四种确定性风格预设、`style_report.json`、浏览器不兼容输入的审核代理、确认摘要与媒体身份双校验、透视/遮罩双模式、八种确定性分段特效、中文路径回归。

## Created skill advantages

- **Design advantage**：审核页只能写配置与确认状态，不能启动渲染；权限和状态边界在服务端实现。
- **Validated advantage**：合成夹具通过准备、Range 206、确认、渲染、H.264 输出和时长/分辨率验证。
- **Validated advantage**：在中文路径下跑通完整夹具，并修复了 Windows 输出编码问题。
- **Validated advantage**：单原片夹具自动生成本地框内视频；风格帧与原片平均绝对像素差 52.825，报告确认没有网络或付费生成调用。
- **Hypothesis**：真实双手视频上，自动轨迹加人工关键帧会减少逐帧校正工作量；缺少真实视频准确率和人工评审证据。

## Missing evidence

- 真实双手取景框检测准确率与遮挡鲁棒性。
- 4K、HDR、VFR、长视频和跨浏览器性能。
- 人工盲评、provider-backed 对比和公开安装遥测。

## 0.3.0 character-restyle redesign

2026-08-11 按 `video to video character transformation`、`consistent character restyle video`、`person costume transformation video` 重新检索。统一研究器因本机 Python 3.10 不支持其依赖的 `datetime.UTC` 失败；随后使用 `npx skills find` 完成 skills.sh 检索。SkillsMP 本轮保持 `missing evidence`，没有伪造结果。

重点核验了 `agentspace-so/runcomfy-skills@video-edit` 的 GitHub 原始 `SKILL.md`。该 Skill 把视频编辑按意图路由为通用 restyle、动作迁移、轻量服装/灯光替换，并强调“先写保持目标，再写单一修改方向”、保存原动作/口型/构图、使用真实 provider trace 和逐模型限制。2026-08-11 在对应 skills.sh 页面观察到 12 installs，在 GitHub 页面观察到 4 stars；另一个 `prime-skills/...@video-edit` 目录结果显示 400.9K installs，但未验证二者的规范镜像关系，因此没有合并或借用高数值。

本地 `小云雀-AI创作` 明确包含视频编辑、风格迁移、上传视频、会话确认、credits 闸门、thread/run 轮询与结果下载；它被选为首选运行适配器，但当前环境 `XYQ_ACCESS_KEY` 与 `pippit-tool-cli` 均不可用，provider-backed 结果为 `missing evidence`。

### v0.3 keep / adapt / reject / invent

- `keep`：原动作、构图、口型和时间关系优先；单次明确编辑方向；保存 provider trace；实际视频必须人工观看。
- `adapt`：把通用 video restyle 路由改造成“角色/画面风格选择 → 外部生成授权 → 转绘 QA → 手势框审核”。
- `reject`：P-broll 内置风格、本地半调/剪纸/像素滤镜、自动外表性别分类、未经确认上传或扣费、用滤镜冒充角色替换。
- `invent`：明确角色版本目录、`gender_inference_performed=false` 合同、艺术家命名风格的描述性转译、第三方角色原创 fallback、AI 转绘观看勾选的服务端/渲染器双重强制。
