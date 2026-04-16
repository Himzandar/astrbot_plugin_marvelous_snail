![:name](https://count.getloli.com/@astrbot_plugin_marvelous_snail?name=astrbot_plugin_marvelous_snail&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# 最强蜗牛插件

astrbot_plugin_marvelous_snail 是一个面向 AstrBot 的微信公众号文章监控插件，当前聚焦于最强蜗牛相关公众号内容。插件通过对接第三方 wechat-article-exporter 风格接口，完成作者搜索、监控作者管理、定时拉取最新文章、自动推送，以及本地文章缓存与查询。

## 项目结构

```
astrbot_plugin_marvelous_snail/
├── main.py            # 插件主逻辑、命令处理和定时任务
├── parse.py           # 消息解析、格式化与中文相关度搜索
├── utils.py           # Cron 文本化工具和消息发送辅助
├── metadata.yaml      # 插件元信息
├── _conf_schema.json  # 配置项定义
└── README.md          # 使用说明
```

## 核心组件

### main.py - 插件主逻辑

`main.py` 是插件的核心模块，包含 `MarvelousSnailPlugin` 主类，继承自 AstrBot 的 `Star` 基类。

#### 主要类和方法

**属性：**
- `config`: 插件配置对象
- `scheduler`: AsyncIOScheduler 定时任务调度器
- `authors`: 搜索结果缓存字典
- `parse`: Parse 实例，用于文章解析

**命令处理方法：**

| 方法 | 命令 | 功能 |
|------|------|------|
| `search_public_account` | `zqwn [关键词] [数量]` | 搜索公众号作者，关键词默认"最强蜗牛" |
| `add_saved_account` | `zqwn_add <索引>` | 将搜索结果中的作者加入监控列表 |
| `del_saved_account` | `zqwn_del <作者名>` | 从监控列表删除指定作者 |
| `list_saved_accounts` | `zqwn_list` | 列出已保存的监控作者 |
| `get_push_list` | `获取推送列表` | 查看当前开启自动推送的会话 |
| `push_zqwn` | `推送zqwn 开启/关闭` | 开启或关闭当前会话的自动推送 |
| `get_strategy` | `搜索攻略 <关键词>` | 搜索本地缓存的文章并分页展示 |

**定时任务方法：**

| 方法 | 功能 |
|------|------|
| `_start_auto_updata_job` | 根据 Cron 表达式注册定时任务 |
| `get_saved_account` | 获取已保存作者的最新文章，比对并推送新文章 |

**消息和数据方法：**

| 方法 | 功能 |
|------|------|
| `_send_message` | 向所有开启推送的用户发送消息 |
| `save_config` | 将文章数据持久化到本地 JSON 文件 |

**生命周期方法：**

| 方法 | 功能 |
|------|------|
| `initialize` | 插件初始化，启动定时任务调度器 |
| `terminate` | 插件卸载，停止定时任务 |

**内部方法（未作为命令公开）：**

| 方法 | 功能 |
|------|------|
| `get_` | 获取指定作者的所有文章并保存到本地（需要管理员权限） |

### parse.py - 消息解析与搜索

`parse.py` 包含 `Parse` 类，提供文章数据的解析、分页和中文相关度搜索功能。

#### 类和方法

**Parse 类：**

| 方法 | 功能 |
|------|------|
| `get_author_all_title_and_link` | 读取本地 JSON 文件，获取指定作者的所有文章标题+简介和链接 |
| `chinese_relevance_score` | 使用 Jaccard 相似度算法计算两个中文字符串的相关度分数 |
| `search_chinese_relevance` | 根据中文相关度对文章数据进行搜索和排序 |
| `parse_title_send_link` | 解析文章标题并返回相关链接列表 |
| `Paging_strategies` | 将攻略列表分页，支持上一页/下一页导航 |

#### 中文相关度搜索说明

`chinese_relevance_score` 方法使用结巴分词对标题和查询词进行分词，然后计算 Jaccard 相似度：

```
相似度 = 交集词数 / 并集词数
```

结果范围为 0 到 1，值越大表示相关性越高。

#### 分页机制

`Paging_strategies` 方法将攻略列表每 5 条分为一页，支持：
- 当前页码和总页码显示
- 上一页/下一页导航
- 返回分页后的消息列表和数据映射

### utils.py - 工具函数

`utils.py` 提供两个工具函数：

#### cron_to_human

将 5 段 cron 表达式转换为中文易读描述。

**参数：**
- `cron`: 5 段 cron 表达式（分 时 日 月 周）

**示例：**
```
0 5 * * *  -> 每天 5点
*/30 * * * * -> 每30分钟
0 8 * * 1-5 -> 周一至周五 8点
```

#### send_msg

发送消息并返回消息 ID，支持 Aiocqhttp 平台特殊处理。

**参数：**
- `event`: 消息事件对象
- `msg`: 要发送的消息内容

**返回：**
- Aiocqhttp 平台成功返回消息 ID
- 其他平台返回 None

## 功能特性

### 已实现功能

- 搜索公众号作者（当前仅支持"最强蜗牛"关键词）
- 添加/删除监控作者
- 查看已保存的监控作者列表
- 按 Cron 表达式定时检查作者是否发布新文章
- 自动推送新文章到已开启推送的私聊或群聊
- 查看当前推送列表
- 搜索本地缓存的文章（基于中文相关度）
- 文章分页浏览和翻页
- 本地 JSON 文件持久化存储
- 请求间隔随机延迟，防止过度请求

### 工作流程

#### 定时更新流程

1. Cron 触发 `get_saved_account` 方法
2. 遍历 KV 存储中的监控作者列表
3. 调用文章接口获取每位作者的最新文章
4. 与 KV 中记录的 aid 比对：
   - 无更新：记录日志并保留旧数据
   - 有新文章：更新本地 JSON 文件，并通过 `_send_message` 推送
5. 请求间隔加入随机延迟（5-10秒）

#### 文章搜索流程

1. 用户发送 `搜索攻略 <关键词>`
2. 读取 `plugin_data` 目录下所有作者 JSON 文件
3. 用户选择作者编号
4. 使用中文相关度算法搜索该作者的所有文章
5. 返回分页后的结果，支持翻页
6. 用户选择文章编号，发送文章链接

## 安装

### 前置条件

- 已安装并可正常运行 AstrBot
- 已准备兼容的公众号文章导出服务
- 导出服务至少提供以下接口：
  - GET `/api/public/v1/account`：搜索公众号作者
  - GET `/api/public/v1/article`：获取公众号文章列表

### 安装步骤

1. 将插件目录放入 AstrBot 的插件目录中，或通过插件市场安装。
2. 重启 AstrBot，或通过插件管理功能加载该插件。
3. 在插件配置中填写 API 地址、认证密钥和定时任务配置。

## 配置说明

插件配置项与 `_conf_schema.json` 保持一致，示例如下：

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
| `updata_cron` | 否 | 定时检查更新的 Cron 表达式，格式为"分 时 日 月 周"；不填则不注册自动检查任务 |

## 命令列表

### 1. 搜索公众号作者

```text
zqwn [关键词] [数量]
```

示例：

```text
zqwn 最强蜗牛 5
```

### 2. 添加监控作者

```text
zqwn_add <索引>
```

### 3. 删除监控作者

```text
zqwn_del <作者名>
```

### 4. 查看监控作者列表

```text
zqwn_list
```

### 5. 开启或关闭自动推送

```text
推送zqwn 开启
推送zqwn 关闭
```

### 6. 查看推送列表

```text
获取推送列表
```

### 7. 搜索攻略

```text
搜索攻略 <关键词>
```

示例：

```text
搜索攻略 源兽
```

流程：
1. 显示已保存的作者列表，回复编号选择作者
2. 搜索该作者所有文章中与关键词相关的内容
3. 分页显示相关攻略，回复编号选择或翻页
4. 选择后发送文章链接

## 数据存储

### KV 存储键

| 键名 | 说明 |
|------|------|
| `authors` | 监控中的作者名到 fakeid 的映射 |
| `articles` | 每个作者最近一次已记录文章的信息 |
| `users` | 接收自动推送的会话信息 |

### 本地文件存储

插件会在 AstrBot 数据目录下写入：

```text
data/plugin_data/astrbot_plugin_marvelous_snail/
```

每个作者对应一个 JSON 文件，例如：

```text
data/plugin_data/astrbot_plugin_marvelous_snail/最强蜗牛.json
```

文件结构：

```json
{
   "num": 3,
   "articles": [
      {
         "aid": "xxx",
         "title": "文章标题",
         "digest": "文章摘要",
         "link": "文章链接",
         "author_name": "作者名称"
      }
   ]
}
```

## 依赖

| 依赖 | 说明 |
|------|------|
| aiohttp | 异步 HTTP 请求库 |
| apscheduler | 定时任务调度库 |
| jieba | 中文分词库，用于文章相关度搜索 |
| AstrBot API | 插件框架提供的 API |

## 注意事项

- 搜索命令目前只接受"最强蜗牛"这一固定关键词
- 自动检查任务是否注册，取决于 `updata_cron` 是否配置有效
- 如果没有配置推送用户，即使检测到新文章，也不会发送消息
- 推送消息分两条发送：一条文章链接，一条作者、标题和简介
- 自动轮询作者时，请求间隔会在基础延时上增加随机抖动
- 私聊场景下，推送列表里展示的标识是发送者名称
- 文章搜索使用中文相关度算法，基于结巴分词和 Jaccard 相似度
- 攻略分页每页显示 5 条，支持翻页导航
- 选择超时时间为 20 秒

## 📄 许可

本项目遵循 MIT License。
