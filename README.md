# 手势框角色转绘视频

用户只需上传一条人物原片，然后选择一个或多个原创角色原型或描述性画面风格。每种风格生成一条与原片动作、构图、空间位置和全局时间对齐的完整转绘视频。最终双手四边形只充当动态窗口：框内显示同位置的风格化层，框外保持原片。

多角色模式会从手框完全展开时开始，把剩余时长平均分给所有角色，通常约每 1–2 秒切换一次并带很短的交叉淡化。切到第 N 条转绘片时读取它在成片当前时刻的画面，不从第 0 秒重播；最后一个角色保持到结尾。角色替换型方案允许脸型、五官、发色、发型、妆容、服装和身份显著变化，只固定动作骨架、人物占位、双手指尖、镜头和时序。

这里不是把风格化视频缩小或透视拉伸后塞进手框。两层视频始终铺满同一画幅并同步播放，手势只改变风格化层的可见范围。

窗口保留完整的开合过程：只要同时检测到两只手，就用两侧食指尖和拇指尖形成四角。手指尚未张开时，它是一条几像素厚的细线；拇指和食指分开后，遮罩连续扩张为四边形。短暂丢检可以保持不足 0.6 秒，只有双手持续缺失时才关闭。

## 你可以直接这样说

- 只用这条原片，把人物做成原创都市蒙面漫画英雄，放进双手框里。
- 我提到蜘蛛侠时，只保留都市超级英雄漫画感觉，角色设计必须原创。
- 把人物转绘成原创高科技装甲英雄，再做手指取景框效果。
- 做成宫崎骏电影那种温暖手绘动画感觉。
- 用六个明显不同的原创女性角色做转绘，手框展开后每 1–2 秒轮换一个。
- Seedance 只能生成 10 秒，先把原片裁成新的 10 秒输入，不要改源文件。

最后一个请求会转译成不点名艺术家的“温暖手绘奇幻日系动画”特征，不要求模型复制个人画风。

现有 IP 名称和命名画风只作为本地意图信号：提交给视频模型前会改写为原创原型和一般视觉特征，不发送角色名称、标志、经典配色或精确服装设计。

## 角色与画面风格

- 原创都市蒙面漫画英雄。
- 原创高科技装甲英雄。
- 温暖手绘奇幻日系动画。
- 经典美式超级英雄漫画。
- 复古日式特摄英雄。

完整目录见 `assets/style-catalog.json`。

## 关于人物性别

Skill 不会从脸、身体或穿着判断人物性别。原因是外表不能可靠代表性别身份，也不应据此自动分类。

当用户提出现有角色时，Skill 不会判断原片人物性别，也不会生成该现有角色。它只保留广义题材方向：都市英雄类转为原创都市蒙面漫画英雄，动力装甲类转为原创高科技装甲英雄。用户仍然只需上传一条视频。

## 整数秒输入

Seedance 等 Provider 只支持 10/11 秒整数档位时，先生成独立的新输入，绝不覆盖源文件。选择最接近且不超过原片的可用时长；若已有生成片，则与生成档位保持一致。

```bash
python scripts/prepare_integer_source.py \
  --source "/path/source.mp4" \
  --seconds 10 \
  --output "/path/source-10s.mp4"
```

## 实际生成能力

角色转绘必须使用视频编辑/视频转视频模型。本 Skill 优先把请求交给已安装的 `小云雀-AI创作` 后端 Agent；提交前必须取得媒体上传和 credits 消耗确认。当前环境没有可核验的 Provider 任务 ID、模型页面或 credits 记录。一条由用户手动生成并回传的真实原创漫画角色转绘视频已经完成媒体 QA、实拍手势跟踪、审核、渲染和用户确认；这证明本条本地流程可用，但不能作为指定模型或跨项目稳定性的 Provider-backed 证据。

没有可用平台时会停在 `transformation_request.json` 与 `provider_message.txt`，不会退回本地滤镜冒充角色转绘。

## 典型流程

```bash
python scripts/prepare_transform_request.py \
  --source "/path/source.mp4" \
  --style-id original-urban-comic-hero \
  --usage personal \
  --output-dir "/path/transform"
```

视频编辑平台返回实际视频后：

```bash
python scripts/verify_transform_output.py \
  --request "/path/transform/transformation_request.json" \
  --video "/path/transform/transformed_inside.mp4" \
  --provider xyq-backend-agent \
  --thread-id THREAD_ID --run-id RUN_ID --external-confirmed

python scripts/prepare_project.py \
  --source "/path/source.mp4" \
  --inside "/path/transform/transformed_inside.mp4" \
  --transform-request "/path/transform/transformation_request.json" \
  --transform-verification "/path/transform/transform_verification.json" \
  --output-dir "/path/project"
```

多角色时重复传入同一组参数；顺序就是成片轮换顺序：

```bash
python scripts/prepare_project.py \
  --source "/path/source-11s.mp4" \
  --inside "/path/style-01/transformed_inside.mp4" \
  --transform-request "/path/style-01/transformation_request.json" \
  --transform-verification "/path/style-01/transform_verification.json" \
  --inside "/path/style-02/transformed_inside.mp4" \
  --transform-request "/path/style-02/transformation_request.json" \
  --transform-verification "/path/style-02/transform_verification.json" \
  --output-dir "/path/project"
```

随后启动审核页、等待用户确认、渲染并运行 `verify_output.py`。

## 质量检查

- 自动检查：时长、比例、编码、文件大小、画面确实发生变化、请求与输出身份一致；多角色还检查每种风格都进入时间线、两两画面差异代理值，以及轨迹已有的旋转自交没有在渲染阶段消失。
- 人工检查：原创角色方向是否正确、是否意外出现现有 IP 识别特征、动作/口型/镜头是否保持、脸和手是否稳定、是否闪烁、是否增删人物、是否出现文字或水印。
- 手势框审核：AI 转绘接受勾选、四角轨迹、全画面对齐遮罩、内外反转、特效和音频。

真实制作前请读取 `references/production-success-playbook.md`。其中固化了本次验证过的关键顺序：先锁定整数秒唯一原片，再做全画面对齐转绘；先拒绝错位转绘片，再进入手势跟踪；最后对双手缺失、细线、展开中、完全展开和后段移动做五类抽查。

## 安装与验证

需要 Python 3.10+、ffmpeg、ffprobe，以及 `requirements.txt` 中的 OpenCV/NumPy。公开发布后预期安装形式为 `npx skills add <owner/repo@handframe-character-video>`；当前仍是本地版本。

发布或安装前请确认：

- [ ] 已安装 Python 3.10 或更高版本。
- [ ] `ffmpeg` 与 `ffprobe` 可在命令行使用。
- [ ] 已安装 `requirements.txt` 中的 OpenCV 与 NumPy。
- [ ] 需要外部视频转绘时，已配置可用 Provider，并取得媒体上传和 credits 消耗授权。
- [ ] 不使用摄像头，也不根据人物外表推断敏感属性。

```bash
python -m unittest discover -s tests -v
python scripts/self_test.py
python /path/to/qiaomu-meta-skill/scripts/validate_skill.py .
python /path/to/qiaomu-meta-skill/scripts/trigger_eval.py . --cases evals/trigger_cases.json
```

## Troubleshooting

- 没有视频编辑平台或凭据：停在请求包，等待配置；不要退回滤镜。
- 现有 IP 请求：提交前自动映射为原创原型；如果原创结果仍因相似性被平台拒绝，进一步更换配色、徽章、面罩、材质和环境符号，不绕过平台限制。
- Provider 只支持整数秒：用 `prepare_integer_source.py` 制作新输入，并用该裁后文件贯穿转绘请求、审核和最终合成。
- 转绘视频时长或比例不合格：不进入手势框项目，重新生成或取得用户明确处理方案。
- 转绘视频闪烁或角色漂移：不能只看自动报告，必须人工拒绝并重试。
- 框内人物被压扁或拉斜：这是旧版透视映射，不是目标效果；0.5.0 起旧配置会自动迁移为全画面对齐遮罩。
- 细线阶段突然跳成大框：确认检测器没有用面积阈值丢弃闭合手势；双手存在时必须记录 `line/opening/open`，并对零面积四边形增加最小厚度，而不是换成默认框。
- 旋转动作被“稳定”成普通矩形：这是把语义指尖误按几何角度重排或凸包化；恢复左食指、右食指、右拇指、左拇指的固定连接顺序。先对照原片，只有无对应动作的坐标尖峰才平滑。
- 多条转绘片看起来只是同一人物换装：重新加强脸型、五官气质、发色发型、妆容、服装结构、材质和环境符号的差异。像素差异门禁通过不等于角色审美区分度通过，仍需逐条人工拒收或接受。
- 没检测到双手：审核页保留人工四角校正。

## 上游参考与独立实现

声明的上游参考：`https://www.zhuzhu.store/; local:chengfeng-videocut-skills/剪口播; local:小云雀-AI创作; https://github.com/agentspace-so/runcomfy-skills/tree/main/video-edit; https://github.com/openclaw/openclaw/tree/main/skills/video-frames; https://github.com/majiayu000/claude-skill-registry/tree/main/skills/ai-ml/mediapipe-usage; https://github.com/jianshuo/claude-skills/tree/main/wjs-reframing-video`。

只吸收视频编辑路由、身份/动作保持、人工审核和证据边界。没有复制第三方 Skill 脚本，也没有使用 P-broll 的内置风格。

## 许可证

本 Skill 以 [MIT License](LICENSE) 发布。外部视频、转绘模型输出及第三方素材仍分别受其来源条款约束。
