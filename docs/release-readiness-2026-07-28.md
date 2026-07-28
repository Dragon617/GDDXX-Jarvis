# GDDXX-Jarvis 0.3.1 开源前检查报告

检查日期：2026-07-28（Asia/Shanghai）

## 结论

`0.3.1` 候选版本已通过源码、桌面、视觉、打包运行时、安装包和本地语音资源验证，可以作为下一次 Windows x64 公开版本。正式创建 GitHub Release 前仍建议配置 Windows 代码签名证书；当前未签名安装包可能触发 SmartScreen 提示。

## 本次修复

1. 完成第 22 轮首次配置纠错反馈，用户修改模型、密钥、URL 或语音方式后会清除过期错误。
2. 修复本地 Whisper 预热调用缺少 `startVoiceServer` 导入造成的未处理异常。
3. 加强桌面关闭探针，启动日志出现未处理 Promise、`ReferenceError` 或未捕获异常时必须失败。
4. 将打包体验中的版本检查改为读取真实应用版本，移除固定 `0.3.0` 的脆弱判断。
5. 版本提升为 `0.3.1`，同步包锁和发布说明。
6. GitHub Actions 发布分支改为默认 `main`。
7. 统一许可证版权名称为 `GDDXX-Jarvis Project`。
8. 删除 README 中可能造成项目来源误解的表述，明确运行时完全位于本仓库。
9. 新增 `CONTRIBUTING.md`，说明开发、验证、密钥和第三方许可要求。
10. 新增 `SECURITY.md`，建立私密漏洞报告流程。

## 验证证据

- `npm audit --omit=dev --audit-level=high --registry=https://registry.npmjs.org`：0 个已知漏洞。
- `npm run check`：通过。
- `npm run check:ui-contracts`：10 组 UI 合约通过。
- `npm run check:2026-07-23-contracts`：21 组迭代合约通过。
- `npm run probe:core`、`probe:desktop`、`probe:desktop-close`：通过，启动和退出无未处理异常。
- `npm run probe:layout`：最小窗口、标准窗口、设置、首次配置、语音恢复、对话和工程模式全部通过。
- `npm run verify:voice-bundle`：内置 Python、Whisper tiny、Jarvis TTS 和本地 ASR 依赖全部存在。
- `npm run probe:packaged-runtime`：打包资源完整，私有配置未进入安装包。
- `npm run probe:packaged-experience`：品牌、动态版本、箭头入口、核心在线、唤醒资源与可见错误检查通过。
- `npm run probe:wake-sequence:packaged`：打包程序唤醒到工作台流程通过，显示版本 `0.3.1`。

视觉证据位于 `.cache/layout-probe/`，包括 `jarvis-layout-minimum.png`、`jarvis-layout-standard.png`、`jarvis-layout-settings.png` 和 `jarvis-layout-first-run.png`。

## 最终产物

- 安装包：`dist/GDDXX-Jarvis-Windows-x64-Setup-0.3.1.exe`
- 大小：480,252,227 字节
- SHA-256：`3e6437f52512d0c51e8919c89db6abe8c3643ef10615b9477ea57cd3f91c6944`
- 校验文件：`dist/GDDXX-Jarvis-Windows-x64-Setup-0.3.1.exe.sha256`

## 发布风险

- 安装包当前未签名。用户应从本仓库 GitHub Releases 下载并核对 SHA-256；维护者应在扩大公开分发前配置可信代码签名。
- 自动化已覆盖 Windows 10/11 x64 的部署约束和打包资源，但无法证明所有第三方杀毒软件、声卡驱动和企业策略组合都兼容。
- 首次对话仍需要用户自己的模型服务 API Key；本地语音识别和 Jarvis TTS 已随安装包提供。
