# GR III 胶片固件魔改工具(Duccio 版)

[English](README.md) | **简体中文**

为理光 GR III(固件 2.10)打造的胶片模拟固件工具:内置 **Duccio 自研胶片**(Kodak Portra 400、Kodak Ektar 100、Kodak Vision3 5207、Kodak Vision3 5219)+ **机内原生颗粒引擎** + **本地网页构建工具**,全程离线生成可刷写固件。

## 项目构成

本项目基于 [idontknownihil/gr3-film-mods](https://github.com/idontknownihil/gr3-film-mods)(MIT 许可)的 GR III 固件逆向研究成果构建,在此之上自主研发了三部分:

### 1. 机内原生颗粒引擎(原创,上游无此功能)
- 让所有胶片槽位复用机内「颗粒效果」菜单(关闭/弱/中/强 四档)
- 逆向了颗粒的三类参数存储(档位枚举 / 附属参数 / 强度),按胶片 tone 逐一写入
- 修复了菜单列表、gate 分发、RTOS 空间分配三层问题,全部通过离线仿真验证

### 2. Duccio 胶片线(原创数据)
- **Portra 400**、**Ektar 100**、**Vision3 5207(电影)**、**Vision3 5219(夜色)** 四款胶片
- 拟合数据来自自建校色流程(色卡实拍 → .cube → 12 分区色相 joint/lab 拟合),非第三方 LUT 衍生
- 每款胶片含风格矩阵、色调曲线、曲线后 3x3 矩阵与 12 分区色相矩阵(hue_q10)

### 3. 本地网页构建工具(原创)
- `server.py + index.html`:浏览器里选胶片、一键生成固件、下载刷机
- 支持 XMP / .cube 导入 → 自动拟合为新胶片 → 进固件
- ΔE 看板、胶片库管理、官方固件导入引导、Mac/Windows 启动脚本

## 使用

见 `Mac使用说明.txt`(装 Python → 双击安装依赖 → 放官方固件 → 双击启动)。
需要自备理光官方固件 `fwdc239b.bin`(2.10),本仓库不包含、也不分发任何理光固件。

## 许可(按部分)

- 引擎代码与笔记:GPL-2.0(因链接 [gr-custom-tool](https://github.com/DoYitNow/gr-custom-tool)(GPL-2.0)与 Unicorn(GPLv2))。上游 GR III 逆向研究部分版权归 idontknownihil(MIT),本仓库的增量部分版权归 Duccio(Du Yuanjun)。
- `work/films_v16/fits/duccio/`、`work/duccio/` 等 Duccio 胶片拟合数据:版权归 Duccio,**保留所有权利**(不随 GPL 分发,商业使用需授权)。
- `third_party/gr-custom-tool`:GPL-2.0(随仓库分发,保留其自身许可)。
- 不包含任何理光固件、修补固件镜像或照片。

## 免责声明

非官方逆向工程研究。刷入修改固件可能导致相机永久变砖、失去保修。补丁仅经离线仿真与单台相机验证,不保证在你的设备上可用或安全。使用风险完全自负;与理光映像无任何关联。
