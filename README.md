# EZVIZ CN Home Assistant 自定义集成

这是基于 Home Assistant 官方 `homeassistant/components/ezviz` 复制出来的自定义集成，域名改为 `ezviz_cn`，默认接入中国区萤石云 `api.ys7.com`，并依赖 CN 适配版 `pyezvizapi`。

## 安装

1. 将 `custom_components/ezviz_cn` 放到 Home Assistant 配置目录的 `custom_components/ezviz_cn`。
2. 重启 Home Assistant。
3. 在「设置 -> 设备与服务 -> 添加集成」中搜索 `EZVIZ CN`。
4. 使用萤石云中国区账号登录，默认 URL 为 `api.ys7.com`。

## 注意

- 不建议同时启用官方 `EZVIZ` 集成和本集成，因为两者都会安装同名 Python 包 `pyezvizapi`。
- 当前依赖直接指向 `https://github.com/liuzexier/pyEzvizApiCN.git@main`。发布稳定版本后，建议把 `manifest.json` 中的依赖改成 tag，例如 `@v0.1.0`。
- 如果 Home Assistant 环境无法从 GitHub 安装依赖，可以先把 CN 版 `pyezvizapi` 发布到 PyPI，或在 HA 容器/虚拟环境里手动安装。
