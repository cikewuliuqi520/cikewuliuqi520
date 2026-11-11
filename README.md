## Hi 👋 我是杨磊

全栈开发工程师，热爱用技术解决实际问题。

### 🔧 技术栈

![Java](https://img.shields.io/badge/-Java-007396?style=flat-square&logo=java&logoColor=white)
![Spring](https://img.shields.io/badge/-Spring-6DB33F?style=flat-square&logo=spring&logoColor=white)
![TypeScript](https://img.shields.io/badge/-TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Next.js](https://img.shields.io/badge/-Next.js-000000?style=flat-square&logo=next.js&logoColor=white)
![React](https://img.shields.io/badge/-React-61DAFB?style=flat-square&logo=react&logoColor=black)
![Python](https://img.shields.io/badge/-Python-3776AB?style=flat-square&logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)
![FFmpeg](https://img.shields.io/badge/-FFmpeg-007808?style=flat-square&logo=ffmpeg&logoColor=white)

### 🚀 个人项目

- [video-auto-publisher](https://github.com/cikewuliuqi520/video-auto-publisher) — 一键文生视频自动发布系统（Next.js + DeepSeek + FFmpeg）
- [ supermarket-voice-assistant](https://github.com/cikewuliuqi520/supermarket-voice-assistant) — 超市语音助手 - 支持语音查价、智能对话、商品管理


### 🌐 Clash 网络优化 Skill

给 Windows 或 Mac 上的 Clash Party / mihomo 选择可用且稳定的 OpenAI 节点。单次执行有 20 秒截止时间；测速失败时保留或恢复原节点。节点维护表保存在使用者自己的电脑上，不包含订阅码或密钥。

Codex 用户一键安装：

```bash
npx --yes skills add cikewuliuqi520/cikewuliuqi520 --skill clash-network-optimize --agent codex --global --yes
```

Windows PowerShell 中使用：

```powershell
npx.cmd --yes skills add cikewuliuqi520/cikewuliuqi520 --skill clash-network-optimize --agent codex --global --yes
```

安装后对 Codex 说「优化下网络问题」，或明确说「优化 OpenAI 的 Clash 节点」。

要求 Node.js/npm、Python 3、curl 和已启动的 Clash Party / mihomo。Windows 客户端还需启用本机控制 API；常见端口会自动发现，自定义端口可用 `CLASH_CONTROLLER` 指定。节点表在 Windows 的 `%LOCALAPPDATA%\clash-network-optimize\nodes.json` 或 Mac 的 `~/.cache/clash-network-optimize/nodes.json`，每台电脑独立维护。详见 [Skill 说明](skills/clash-network-optimize/SKILL.md)。
