![:name](https://count.getloli.com/@astrbot_plugin_marvelous_snail?name=astrbot_plugin_marvelous_snail&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# 最强蜗牛插件

astrbot_plugin_marvelous_snail 是一个面向 AstrBot 的微信公众号文章监控插件，当前聚焦于最强蜗牛相关公众号内容。插件通过对接第三方 wechat-article-exporter 风格接口，完成作者搜索、监控作者管理、定时拉取最新文章、自动推送，以及本地文章缓存与查询。

## ✨ 功能概览

- 搜索公众号作者，当前仅允许关键词为“最强蜗牛”
- 将搜索结果中的作者加入监控列表
- 删除已监控作者
- 查看当前已保存的监控作者列表
- 按 Cron 表达式定时检查作者是否发布新文章
- 向已开启推送的私聊或群聊自动发送最新文章
- 查看当前开启自动推送的会话列表
- 查询本地缓存中的作者，并按编号获取该作者最新一篇文章
- 将作者文章以 JSON 文件形式持久化到 AstrBot 数据目录

## 工作方式

插件运行时主要依赖两类数据：

- KV 存储：保存监控作者、最近一次已记录文章、推送会话列表
- 本地 JSON 文件：保存作者文章归档，路径为 data/plugin_data/astrbot_plugin_marvelous_snail/

定时任务触发后，插件会依次读取已保存作者列表，调用文章接口拉取每位作者最近一篇文章，并与 KV 中记录的 aid 对比：

- 如果没有更新，只记录日志
- 如果检测到新文章，会更新本地缓存，并向所有已启用推送的会话发送文章链接和摘要

为了降低请求过于规律带来的风险，轮询作者时会在请求之间插入随机等待。

## 安装

### 前置条件

- 已安装并可正常运行 AstrBot
- 已准备兼容的公众号文章导出服务
- 导出服务至少提供以下接口：
   - GET /api/public/v1/account：搜索公众号作者
   - GET /api/public/v1/article：获取公众号文章列表

### 安装步骤

1. 将插件目录放入 AstrBot 的插件目录中，或通过插件市场安装。
2. 重启 AstrBot，或通过插件管理功能加载该插件。
3. 在插件配置中填写 API 地址、认证密钥和定时任务配置。

## ⚙️ 配置说明

插件配置项与 _conf_schema.json 保持一致，示例如下：

```json
{
   "exporter_api_url": "http://localhost:3000",
   "exporter_auth_key": "your-auth-key",
   "updata_cron": "0 5 * * *"
}
```

| 配置项 | 必填 | 说明 |
| --- | --- | --- |
| `exporter_api_url` | 是 | wechat-article-exporter API 根地址，不要带结尾斜杠 |
| `exporter_auth_key` | 是 | 请求头 `X-Auth-Key` 使用的认证密钥 |
| `updata_cron` | 否 | 定时检查更新的 Cron 表达式，格式为“分 时 日 月 周”；不填则不注册自动检查任务 |

说明：

- 默认配置中的 exporter_api_url 为 http://localhost:3000
- 默认 Cron 为 0 5 * * *，即每天 5:00 执行一次检查
- 搜索命令会显式校验 exporter_api_url 和 exporter_auth_key 是否已配置

## 命令列表

### 1. 搜索公众号作者

```text
zqwn [关键词] [数量]
```

示例：

```text
zqwn 最强蜗牛 5
```

说明：

- 关键词默认是最强蜗牛
- 数量默认是 5
- 当前实现中，如果关键词不是最强蜗牛，插件会直接拒绝
- 搜索结果会缓存到当前插件实例内存中，后续可用 zqwn_add 按编号添加

### 2. 添加监控作者

```text
zqwn_add <索引>
```

作用：

- 将最近一次 zqwn 搜索结果中的指定编号作者加入监控列表

注意：

- 该命令依赖当前进程中的搜索结果
- 如果没有先执行过 zqwn，或索引无效，会提示错误

### 3. 删除监控作者

```text
zqwn_del <作者名>
```

作用：

- 从监控列表中移除指定作者
- 如果该作者在 KV 文章记录中存在，也会一并删除对应记录

### 4. 查看监控作者列表

```text
zqwn_list
```

作用：

- 列出当前已保存的全部监控作者名称

### 5. 开启或关闭自动推送

```text
推送zqwn 开启
推送zqwn 关闭
```

作用：

- 为当前私聊或群聊开启或关闭自动推送

行为细节：

- 群聊场景下，插件以 group_id 作为推送标识
- 私聊场景下，插件使用发送者名称作为标识保存，同时保存 unified_msg_origin 用于实际回发消息

### 6. 查看推送列表

```text
获取推送列表
```

作用：

- 输出当前已启用自动推送的会话标识列表

### 7. 查看最新攻略

```text
最新攻略zqwn
```

作用：

- 读取本地缓存目录中的作者 JSON 文件
- 先发送作者编号列表
- 用户回复编号后，返回该作者当前缓存中的最新一篇文章链接和摘要

交互细节：

- 选择超时时间为 10 秒
- 在 OneBot v11 场景下，作者选择消息会在约 10 秒后尝试撤回
- 当前返回的是该作者缓存中的最新一篇文章，不是按关键词检索文章

## 典型使用流程

1. 配置 exporter_api_url、exporter_auth_key 和 updata_cron。
2. 使用 zqwn 最强蜗牛 5 搜索目标作者。
3. 使用 zqwn_add 1 之类的命令将作者加入监控。
4. 在需要接收通知的会话中执行 推送zqwn 开启。
5. 等待定时任务自动检查更新。
6. 如需查看已缓存的最新文章，可执行 最新攻略zqwn。

## 数据存储

### KV 存储键

- authors：监控中的作者名到 fakeid 的映射
- articles：每个作者最近一次已记录文章的信息
- users：接收自动推送的会话信息

### 本地文件存储

插件会在 AstrBot 数据目录下写入：

```text
data/plugin_data/astrbot_plugin_marvelous_snail/
```

每个作者对应一个 JSON 文件，例如：

```text
data/plugin_data/astrbot_plugin_marvelous_snail/最强蜗牛.json
```

文件结构大致如下：

```json
{
   "num": 3,
   "articles": [
      {
         "aid": "xxx",
         "title": "文章标题",
         "digest": "文章摘要",
         "link": "文章链接"
      }
   ]
}
```

说明：

- 新文章会插入到数组头部
- 最新攻略zqwn 读取的就是这些本地缓存文件

## 已实现但未开放为正式命令的能力

main.py 中还保留了一个未注册命令的调试方法 get_：

- 它可以分页拉取某作者全部文章并写入本地 JSON
- 当前没有对外暴露 command 装饰器，默认不会作为正式指令使用

parse.py 中还存在标题相似度检索的辅助逻辑，但当前主流程没有接入该能力，因此 README 不将其视为对外功能。

## 注意事项

- 搜索命令目前只接受“最强蜗牛”这一固定关键词
- 自动检查任务是否注册，取决于 updata_cron 是否配置有效
- 如果没有配置推送用户，即使检测到新文章，也不会发送消息
- 推送消息分两条发送：一条文章链接，一条作者、标题和简介
- 自动轮询作者时，请求间隔会在基础延时上增加随机抖动
- 私聊场景下，推送列表里展示的标识是发送者名称，不一定是用户数字 ID

## 项目文件

```text
astrbot_plugin_marvelous_snail/
├── main.py            # 插件主逻辑、命令和定时任务
├── parse.py           # 消息格式化与交互辅助逻辑
├── utils.py           # Cron 文本化工具
├── metadata.yaml      # 插件元信息
├── _conf_schema.json  # 配置项定义
└── README.md          # 使用说明
```

## 依赖

- aiohttp
- apscheduler
- jieba
- AstrBot API

以上依赖通常由 AstrBot 运行环境或插件环境提供。

## 📄 许可

本项目遵循 MIT License。
