# 手势框角色转绘视频：中文使用教程

这个 Skill 把一条人物实拍视频做成“用双手打开一个风格化世界”的短视频：画框外保持原片，画框内显示与原片动作、构图和时间完全对齐的角色转绘画面。它还支持准备多条风格化视频，并在手框内约每 1–2 秒切换一个角色。

它不是普通画中画，也不会把转绘视频压扁、旋转或透视塞进手框。原片和转绘片始终全屏、同位置、同时间播放，双手四边形只负责控制哪些区域可见。

## 最适合哪些视频

- 竖屏人物视频，人物的上半身和双手清晰入镜。
- 双手先靠近形成线段，再逐渐展开成四边形。
- 想把人物变成一个原创角色，或依次展示多个明显不同的原创角色。
- 已经有风格化转绘片，想完成手框跟踪、审核和渲染。

以下情况不适合直接使用：实时摄像头滤镜、只有单手的视频、双手长期离开画面、普通画中画，以及不需要手势框的整片转绘。

## 最终会得到什么

项目完成后，主要文件如下：

```text
project/
├── tracking.json             # 双手四角轨迹
├── review_config.json        # 审核页配置
├── review_confirmed.json     # 用户确认记录
├── render_report.json        # 渲染证据
├── verification.json         # 最终自动验证
└── output.mp4                # 最终成片
```

多风格项目还会保存每条转绘片对应的请求和验证报告。

## 安装

从 GitHub 安装到 Codex：

```bash
npx skills add Pakyu/handframe-character-video --skill handframe-character-video --global --yes
```

更新已经安装的版本：

```bash
npx skills update handframe-character-video --global --yes
```

本地脚本还需要：

- [ ] Python 3.10 或更高版本。
- [ ] `ffmpeg` 与 `ffprobe` 可在命令行使用。
- [ ] OpenCV 与 NumPy；在仓库目录运行 `python -m pip install -r requirements.txt`。
- [ ] 一条用户明确提供的人物原片。
- [ ] 若使用外部视频模型，已经取得上传媒体和消耗 credits 的许可。

摄像头不是依赖，本 Skill 明确不读取摄像头。

## 你可以直接这样说

安装后上传一条原片，然后告诉 Codex：

```text
使用“手势框角色转绘视频”处理这条原片。
做三个明显不同的原创女性奇幻角色，环境也跟随角色改变；
动作、人物位置、双手指尖、镜头和时间必须与原片一致；
手框完全展开后每 1–2 秒切换一个角色。
```

如果你只想做一个角色：

```text
使用“手势框角色转绘视频”处理这条原片。
把人物转绘成原创霓虹机械歌姬，只在双手框内显示转绘画面。
```

如果你已经手动生成了转绘视频：

```text
这是原片和我手动生成的五条转绘片。
使用“手势框角色转绘视频”建立审核项目，按上传顺序在手框内轮换。
```

接下来 Codex 会检查素材、建立审核页。你需要逐条观看转绘片，检查四角轨迹和切换节奏，然后明确说“确认审核”和“开始渲染”。

## 角色和画风怎么选

推荐使用描述清楚的原创角色方案，例如：

- 星夜水晶学院炼金师：冷色水晶、学院礼服、星空实验室。
- 霓虹机械虚拟歌姬：机械发饰、发光材质、未来舞台。
- 东方月华花灵：月白长发、花瓣衣饰、东方月夜庭院。
- 银月蔷薇术士：深色礼服、银色符文、蔷薇魔法空间。
- 温暖手绘奇幻动画：柔和线条、水彩质感、自然光和生活感动作。

多角色要真正拉开差异，不要只写“换一套衣服”。至少同时改变脸型与五官气质、发色发型、妆容、服装结构、材质、身份和环境符号。

现有影视、漫画、游戏角色或艺术家名字只会被当作本地意图信号。提交给视频模型前必须改写成原创角色原型或一般视觉特征，不复制名称、标志、经典配色、精确服装或个人画风。

Skill 不会根据脸、身材或穿着推断人物性别。需要特定角色呈现时，请由用户直接说明角色设定。

## 完整手动流程

下面适合想自行运行脚本或排查问题的用户。所有命令都在仓库根目录执行。

### 第一步：必要时裁成整数秒

部分视频模型只接受 10 秒、11 秒等整数档位。请创建新文件，不要覆盖原片：

```bash
python scripts/prepare_integer_source.py \
  --source "D:/video/source.mp4" \
  --seconds 11 \
  --output "D:/video/source-11s.mp4"
```

从这一步开始，转绘、跟踪、审核和渲染必须始终使用同一条裁后原片。

### 第二步：为每种风格创建转绘请求

```bash
python scripts/prepare_transform_request.py \
  --source "D:/video/source-11s.mp4" \
  --style-id neon-mechanical-diva \
  --usage personal \
  --output-dir "D:/video/style-01"
```

输出目录中的 `provider_message.txt` 可以交给支持视频编辑或视频转视频的平台。模型必须使用原片作为唯一动作、时序、摄影机和构图参考。

要做多个角色，就为每个角色重复一次。每种风格都要生成一条完整 11 秒视频，不能只生成最终展示的 1–2 秒片段。

### 第三步：验证模型返回的视频

如果视频由外部平台手动生成并下载：

```bash
python scripts/verify_transform_output.py \
  --request "D:/video/style-01/transformation_request.json" \
  --video "D:/video/style-01/transformed_inside.mp4" \
  --provider manual-return \
  --manual-return
```

如果能取得真实任务 ID、运行 ID 和链接，则改用 `--thread-id`、`--run-id`、`--web-link` 与 `--external-confirmed` 保存 Provider 证据。

自动检查通过后仍要完整观看视频，重点检查：

1. 人物位置、动作、镜头和手指是否与原片同步。
2. 脸、手、服装和背景是否闪烁、融化或突然变化。
3. 是否新增人物、文字、水印或意外切镜。
4. 不同角色是否真的明显不同，而不是同一人物换装。

明显错位的转绘片应该重新生成，不能靠手框透视变形掩盖。

### 第四步：创建审核项目

单风格示例：

```bash
python scripts/prepare_project.py \
  --source "D:/video/source-11s.mp4" \
  --inside "D:/video/style-01/transformed_inside.mp4" \
  --transform-request "D:/video/style-01/transformation_request.json" \
  --transform-verification "D:/video/style-01/transform_verification.json" \
  --output-dir "D:/video/project"
```

多风格时重复传入三组对应参数，传入顺序就是默认播放顺序：

```bash
python scripts/prepare_project.py \
  --source "D:/video/source-11s.mp4" \
  --inside "D:/video/style-01/transformed_inside.mp4" \
  --transform-request "D:/video/style-01/transformation_request.json" \
  --transform-verification "D:/video/style-01/transform_verification.json" \
  --inside "D:/video/style-02/transformed_inside.mp4" \
  --transform-request "D:/video/style-02/transformation_request.json" \
  --transform-verification "D:/video/style-02/transform_verification.json" \
  --output-dir "D:/video/project"
```

每条 `--inside` 必须有一条对应请求和验证报告，三者数量必须相同。

### 第五步：打开审核页

```bash
python scripts/review_server.py "D:/video/project" --port 8167
```

然后打开：

```text
http://127.0.0.1:8167/review.html
```

审核时按以下顺序检查：

1. 逐条播放并勾选接受所有转绘片。
2. 检查手还没张开时，窗口是否先表现为细线，再跟随手指展开。
3. 拖动四个白色圆点校正明显错位的角点。
4. 检查完全展开、快速移动、短暂遮挡和视频后段。
5. 多风格项目检查轮换起点、每段秒数、顺序和淡化时间。
6. 手部旋转时允许上边和下边交叉；不要为了得到规整矩形而把真实旋转抹掉。
7. 确认后点击审核页中的确认按钮。

需要直接查看问题时刻，可以在网址后添加时间，例如：

```text
http://127.0.0.1:8167/review.html?t=7
```

### 第六步：渲染并验证

审核确认后运行：

```bash
python scripts/render_video.py "D:/video/project"
python scripts/verify_output.py "D:/video/project"
```

当 `verification.json` 中的 `ok` 为 `true` 时，技术合同已经通过，成片位于：

```text
D:/video/project/output.mp4
```

最后仍需人工观看成片，至少抽查：双手缺失、细线、展开中、完全展开、角色切换、旋转交叉和后段移动。

## 多风格轮换的工作原理

- 默认从手框首次进入完全展开状态时开始轮换。
- 剩余时间平均分配给全部角色，通常约每 1–2 秒一换。
- 切到第二条转绘片时，读取它在成片当前时刻的画面，不从 0 秒重新播放。
- 所有角色播放完后，最后一个角色保持到结尾，不循环。
- 默认使用约 0.12 秒短交叉淡化，审核页可以调整。
- 最终验证会检查每种风格是否实际进入时间线，并对所有转绘片做两两像素差异抽查。
- 不提供故障、扫描、RGB 分离、像素化等分段特效；画面重点保持在手框揭示与角色轮换本身。

像素差异只用于发现重复文件或几乎相同的结果，不能证明角色设计好看，也不能代替人工审美审核。

## Troubleshooting：常见问题

### 四个白色圆点拖不动

确认浏览器显示的是当前版本的审核页，并直接拖动圆点中心。竖屏视频会按画布实际可见区域换算坐标，旧版缓存页面可以强制刷新后重试。

### 风格化画面突然出现

检查双手闭合阶段是否被错误标记为不可见。正确效果是“细线 → 展开中 → 四边形”，不是等面积达到阈值后突然显示。

### 框内画面被压扁或拉斜

这是透视映射造成的错误效果。正确模式固定为 `fit_mode=clip`：转绘片全画幅对齐，手框只做动态遮罩。

### 7 秒附近框线交叉或像在抽动

先对照原片。如果手指正在真实旋转并交换上下关系，交叉是正确动作，必须保留。四角固定为左食指、右食指、右拇指、左拇指，不能按几何角度重新排序或凸包化。只有原片没有对应动作的单帧大跳，才属于需要平滑的检测尖峰。

### 多个角色看起来差不多

重新强化脸型、五官气质、发色发型、妆容、服装结构、材质和环境符号。不要只改颜色或衣服。即使自动像素差异通过，也应在人审阶段拒收缺乏角色区分度的结果。

### 模型只接受整数秒

先用 `prepare_integer_source.py` 创建新的整数秒输入，让该文件贯穿全部后续步骤。不要改速度，也不要在中途换回原片。

### 没有 Provider 任务记录

手动回传视频仍可完成本地制作，但报告会明确写 `missing evidence`。不得据此宣称使用了某个无法核验的模型或 credits 数量。

### 最终验证通过是否代表视频一定好看

不是。自动验证证明时长、分辨率、编码、文件身份、时间轮换、像素差异代理和旋转交叉等技术合同；人物审美、手指细节和转绘稳定性仍需人工观看。

## 验证 Skill 本身

```bash
python -m unittest discover -s tests -v
python scripts/self_test.py
python ../qiaomu-meta-skill/scripts/validate_skill.py .
```

当前版本包含真实单转绘和五转绘项目经验，但不承诺跨所有人物、动作、视频模型或长视频都能自动得到相同质量。

## 隐私与安全边界

- 不读取摄像头，不实现实时滤镜。
- 不根据人物外表推断性别、年龄、族裔或其他敏感属性。
- 未经明确同意，不上传媒体或消耗外部平台 credits。
- 不把现有 IP、标志、精确服装或在世艺术家姓名提交给生成平台。
- 原片永远不覆盖；裁片、请求、项目和成片均写入新目录。

## 许可证

本 Skill 以 [MIT License](LICENSE) 发布。用户原片、外部模型输出和第三方素材仍分别受其来源条款约束。

## 上游参考

本 Skill 的工作流设计参考了以下公开页面和本地 Skill，但检测、审核与渲染逻辑为独立实现：

`https://www.zhuzhu.store/; local:chengfeng-videocut-skills/剪口播; local:小云雀-AI创作; https://github.com/agentspace-so/runcomfy-skills/tree/main/video-edit; https://github.com/openclaw/openclaw/tree/main/skills/video-frames; https://github.com/majiayu000/claude-skill-registry/tree/main/skills/ai-ml/mediapipe-usage; https://github.com/jianshuo/claude-skills/tree/main/wjs-reframing-video`
