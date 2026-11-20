# 下载管家 Download Butler

<img src="assets/icon.png" width="96" align="right">

Windows 下载文件夹的可视化管理器：**新文件下载完成后自动按类型和年月归档**，还能快速搜索、打开、移动和删除文件，并按天数或容量自动清理旧文件。

## 功能

- **自动整理**：监视“下载”文件夹，新文件下载完成后几秒内归入
  `重要文件 / 安装包 / 压缩包 / 图片 / 视频 / 音乐 / 代码 / 其他文件`，再按 `年-月` 分子文件夹。
  未下载完的文件（`.crdownload`、`.part` 等）和仍被占用的文件会自动跳过，稍后再试。
- **浏览与搜索**：按分类浏览；显示系统图标与图片缩略图；按日期分组；多关键词搜索（Ctrl+F，回车打开第一个结果）。
- **排序与筛选**：点表头按名称 / 分类 / 大小 / 时间排序，再点一次切换正序 / 倒序；可按时间范围和文件大小筛选。
- **文件操作**：打开、打开所在位置、重命名（F2）、移动到分类或任意文件夹、复制路径、删除（Del，进回收站可还原）；可直接把文件拖到其他程序。
- **自动清理**：定期清理超过 N 天的文件，或在总量超过 X GB 时从最旧的开始清理；可设置受保护的分类（默认保护“重要文件”）。
- **外观**：深色 / 浅色主题；自定义背景图片及其可见度；自动从背景图提取强调色，并自动调整明暗保证文字清晰；可调模块与窗口不透明度。
- **后台运行**：关闭窗口后缩到系统托盘；可开机自启。

## 性能

- 不做定时轮询：使用系统的文件夹变化通知，没有新文件时后台 CPU 占用为 0。
- 隐藏在托盘时不刷新界面；开机后台启动约 15 秒后预先准备列表，之后从托盘打开窗口约 0.3 秒。
- 缩略图在后台线程按目标尺寸解码，并缓存到 `%LOCALAPPDATA%\DownloadButler\thumbs`。

## 安装

在 [Releases](../../releases) 下载 `DownloadButler-Setup-x.y.z.exe` 运行即可。安装在当前用户目录，不需要管理员权限。

- 设置与背景图保存在 `%APPDATA%\下载管家`，卸载时保留。
- 系统要求：Windows 10 / 11 x64。

## 从源码运行 / 构建

```powershell
python -m pip install -r requirements.txt
python download_manager.py            # 直接运行
python download_manager.py --min      # 只在托盘中启动
powershell -ExecutionPolicy Bypass -File .\build.ps1   # 打包 exe + 生成安装包（需 Inno Setup 6）
```

安装包输出到 `installer\Output\`。

## 分类规则

| 分类 | 扩展名 |
|---|---|
| 重要文件 | pdf doc docx xls xlsx ppt pptx txt md csv wps et dps rtf odt |
| 安装包 | exe msi msix appx apk dmg iso |
| 压缩包 | zip rar 7z tar gz bz2 xz |
| 图片 | jpg jpeg png gif bmp webp svg heic ico |
| 视频 | mp4 mkv avi mov wmv flv webm |
| 音乐 | mp3 wav flac aac m4a ogg |
| 代码 | py js html css json java c cpp ps1 bat sh |
| 其他文件 | 其余所有文件 |

修改 `download_manager.py` 顶部的 `RULES` 即可调整。
