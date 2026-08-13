# 执行工作流

真实生产任务还必须读取 `production-success-playbook.md`；本文件给出步骤，成功手册给出容易失败的判断点和处理顺序。

## 1. 单原片与一个或多个角色选择

用户只需上传一条人物原片。验证媒体后读取 `assets/style-catalog.json`：

- 已明确角色/风格：直接使用对应 `style-id`。
- 提到现有影视、漫画或游戏角色：只识别其广义题材方向，映射到原创原型；不要追问具体版权角色版本，也不要把名称写入 Provider 提示词。
- 未指定风格：询问一次，不自行选择。
- 要求成片按顺序展示多种角色时，为每种角色创建一条完整时长的独立转绘；所有转绘共用同一原片和全局时间线。
- 要求按性别自动匹配：拒绝外表性别推断，改为用户选择角色版本。
- 蛛网/都市英雄方向映射到 `original-urban-comic-hero`；动力装甲方向映射到 `original-armored-hero`。
- 宫崎骏/吉卜力请求：映射到 `warm-handpainted-fantasy-anime`，只保留一般媒介与情绪特征。

Provider 只接受 10/11 秒等整数档位时，先选择最接近且不超过原片的可用时长；已经有生成片时以其档位为准。始终生成新文件：

```bash
python scripts/prepare_integer_source.py \
  --source "/path/source.mp4" \
  --seconds 10 \
  --output "/path/source-10s.mp4"
```

## 2. 创建转绘请求

```bash
python scripts/prepare_transform_request.py \
  --source "/path/source.mp4" \
  --style-id original-urban-comic-hero \
  --usage personal \
  --output-dir "/path/transform"
```

输出 `transformation_request.json` 和 `provider_message.txt`。请求必须记录 `selection_source=user-explicit`、`gender_inference_performed=false`、平台上传与 credits 需要用户确认。

## 3. 外部视频编辑闸门

优先使用当前已安装的 `小云雀-AI创作`：

1. 检查 `XYQ_ACCESS_KEY` 或其当前官方授权状态，不读取或打印密钥。
2. 向用户展示媒体将上传到外部平台并可能消耗 credits；确认 Provider 提示词只含原创原型或描述性特征。
3. 取得明确同意后，按小云雀 Skill 的视频编辑路线上传唯一原片。
4. 把 `provider_message.txt` 作为已获准的请求原样提交；后端提问时保持同一 thread 转达用户答案。
5. 保存真实 `thread_id`、`run_id`、`web_thread_link`，轮询到真实终态并下载视频。
6. 失败时报告真实错误，不自动换角色、平台或重复消耗。

当前环境没有可用鉴权时停在请求包。手动平台回传也可以继续，但验证报告必须如实标记用户说明的 provider 以及缺失的 trace，不得把用户说明升级为 provider-backed 证据。

## 4. 转绘视频自动 QA

```bash
python scripts/verify_transform_output.py \
  --request "/path/transform/transformation_request.json" \
  --video "/path/transform/transformed_inside.mp4" \
  --provider xyq-backend-agent \
  --thread-id THREAD_ID --run-id RUN_ID --web-link WEB_LINK \
  --external-confirmed
```

自动检查失败不得进入合成。自动通过也不能代替人工观看。

## 5. 创建手势框项目

```bash
python scripts/prepare_project.py \
  --source "/path/source.mp4" \
  --inside "/path/transform/transformed_inside.mp4" \
  --transform-request "/path/transform/transformation_request.json" \
  --transform-verification "/path/transform/transform_verification.json" \
  --output-dir "/path/project"
```

多角色项目重复传入 `--inside`、`--transform-request` 和 `--transform-verification`，三类参数数量必须一致，传入顺序即默认轮换顺序。审核页要求逐条接受全部转绘片。

若同一条原片此前已经生成并人工核对过 `tracking.json`，可传入 `--tracking-json` 复用；脚本会核对分辨率、时长和时间轴。导入轨迹仍必须在当前审核页复核，不能跨不同原片复用。

准备脚本验证请求、转绘报告和视频身份，复制证据到项目，并生成轨迹、审核代理和审核页。

审核与成片的合成语义固定为：

- 原片是底层，转绘片按输出画幅全屏缩放并与原片同位置、同时间播放。
- 多条转绘片都从成片的同一全局时刻取帧；切换角色只改变当前可见的转绘层，绝不重置播放头。
- 默认从轨迹首次进入 `open` 阶段时开始轮换，把剩余时长平均分给所有角色，并使用约 0.12 秒的短交叉淡化；顺序用尽后保持最后一条，不循环。
- 双手四角形成的多边形只是动态 Alpha 遮罩；遮罩内显示转绘层，遮罩外显示原片。
- `detected` 表示同时看到两只手：无论当前面积大小，都使用两侧食指尖与拇指尖形成四角。面积很小时稳定成最小厚度约 0.6% 画幅的细线，随后按真实指尖连续展开。`held` 在短暂丢检期间保持上一几何状态，`default` 才表示双手缺失并关闭窗口。
- 只允许 `fit_mode=clip`，旧版 `perspective` 配置读取后自动迁移为 `clip`。
- 不循环转绘片，不把整条转绘片缩小、旋转或透视拉伸到手框中。

## 6. 双重人工审核

审核页同时要求：

1. 逐条勾选已观看并接受全部 AI 转绘视频。
2. 审核自动/人工双手四角轨迹，以及全画面对齐的动态遮罩预览。

服务器和渲染器都会拒绝缺少 `transform_review.approved=true` 的 AI 转绘项目。确认前不得渲染。

## 7. 渲染与验证

```bash
python scripts/watch_review.py "/path/project" --timeout 3600
python scripts/render_video.py "/path/project"
python scripts/verify_output.py "/path/project"
```

最终验证必须逐条检查明确角色选择、未执行性别推断、转绘自动 QA 和视频身份，并检查多角色全局时间同步、风格覆盖、审核摘要、时长、分辨率和输出编码。

## 8. 输出

```text
transform/
├── transformation_request.json
├── provider_message.txt
├── transformed_inside.mp4
└── transform_verification.json

project/
├── manifest.json
├── transformation_request.json
├── transform_verification.json
├── tracking.json
├── review_config.json
├── review_confirmed.json
├── output.mp4
├── render_report.json
└── verification.json
```

## 9. 限制

- 已有一条用户手动生成并回传的真实原创漫画角色转绘片完成本地全流程和用户审核，但缺生成平台任务 ID、模型页面和 credits 记录，因此不能证明具体模型身份或跨项目稳定性。
- 生成平台的具体模型、整数时长档位、费用和内容政策可能变化，提交前以实时能力为准。
- 真实人物转绘可能出现脸、手、服装、口型和时间一致性问题，必须看实际视频。
