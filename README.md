# 下载管家 Download Butler

<img src="assets/icon.png" width="96" align="right">

Windows 下载文件夹的可视化管理器：**新文件下载完成后自动按类型和年月归档**，还能快速搜索、打开、移动和删除文件，并按天数或容量自动清理旧文件。

## 功能

- **自动整理**：监视“下载”文件夹（也可在设置中改为管理其他文件夹），新文件下载完成后归入
  `重要文件 / 安装包 / 压缩包 / 图片 / 视频 / 音乐 / 代码 / 其他文件`，再按 `年-月` 分子文件夹（可关闭）。
  分类和扩展名可在设置里自由增删改。
  未下载完的文件会自动跳过：支持 Chrome / Edge / Firefox / Safari / Opera、迅雷、FDM、aria2、
  uTorrent、qBittorrent、BitComet 等的临时文件和控制文件。下载完成后默认等 10 秒再整理（可在设置中调整），
  方便直接在浏览器里“打开”或“在文件夹中显示”。
- **浏览与搜索**：按分类浏览；显示系统图标与图片缩略图；按日期分组；多关键词搜索（Ctrl+F，回车打开第一个结果）。
- **排序与筛选**：点表头按名称 / 分类 / 大小 / 时间排序，再点一次切换正序 / 倒序；可按时间范围和文件大小筛选。
- **文件操作**：打开、打开所在位置、重命名（F2）、移动到分类或任意文件夹、复制路径、删除（Del，进回收站可还原）；可直接把文件拖到其他程序。
- **自动清理**：定期清理下载到本机超过 N 天的文件，或在总量超过 X GB 时从最旧的开始清理；可设置受保护的分类（默认保护“重要文件”）。
  - 只移入回收站：放不进回收站的文件（网络盘、U 盘、超过回收站容量）一律跳过，绝不永久删除。
  - 受保护的文件本身已超过容量阈值时，不删除任何文件，只提醒。
  - 不会跟随符号链接 / 目录联接删除下载文件夹以外的文件；清理在后台线程运行，不卡界面。
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
python tests/run_all.py               # 运行测试（全部在临时目录中进行，不动真实文件）
powershell -ExecutionPolicy Bypass -File .\build.ps1   # 打包 exe + 生成安装包（需 Inno Setup 6）
```

安装包输出到 `installer\Output\`。`requirements.txt` 只含运行依赖，打包工具在 `requirements-build.txt`。
推送到 GitHub 后，CI 会在 Windows 上运行测试并构建安装包（`.github/workflows/ci.yml`）。

## 分类规则

在 **设置 → 分类规则** 中可以修改分类名、扩展名，或新增 / 删除分类，保存后自动重启生效：

- 给分类改名时，对应的文件夹会一起改名；删除分类不会删除文件夹和里面的文件。
- 同一个扩展名出现在多个分类时，排在前面的分类优先；没有匹配的文件放进“其他文件”。
- “恢复默认规则”可回到下面的内置规则：

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

## 管理的文件夹

默认管理系统的“下载”文件夹。在 **设置 → 常规 → 管理的文件夹** 中可以换成其他文件夹（例如浏览器单独设置的下载目录）。
为避免误操作，不能选择磁盘根目录、用户主目录本身、系统 / 程序目录以及 AppData 等应用数据目录。
