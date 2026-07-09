# My Agent 项目

一个智能代理项目，包含完整的数据库模式、API 端点、测试和文档。

## 📁 项目结构

```
my_agent/
├── src/
│   ├── api/                 # API 端点
│   │   ├── app.py           # Flask 应用入口
│   │   └── endpoints.py     # API 端点定义
│   ├── database/            # 数据库
│   │   ├── connection.py    # 数据库连接
│   │   └── schema.sql       # 数据库模式
│   └── ...
├── tests/                   # 测试文件
│   ├── test_api.py          # API 测试
│   ├── test_tools.py        # 工具测试
│   └── test_sub_agent.py    # 子代理测试
└── readme/                  # 详细文档
```

## 🗄️ 数据库模式

项目包含以下数据表：

| 表名 | 描述 |
|------|------|
| `users` | 用户管理 |
| `tasks` | 任务管理 |
| `task_dependencies` | 任务依赖关系 |
| `memory_entries` | 内存条目存储 |

## 🔌 API 端点

### Tasks API
- `GET /api/tasks` - 获取所有任务
- `GET /api/tasks/<id>` - 获取单个任务
- `POST /api/tasks` - 创建新任务
- `PUT /api/tasks/<id>` - 更新任务
- `DELETE /api/tasks/<id>` - 删除任务

### Memory API
- `GET /api/memories` - 获取所有内存条目
- `POST /api/memories` - 创建新的内存条目

### Users API
- 完整的 CRUD 操作端点

### Health Check
- `GET /api/health` - 服务健康状态检查

## 🧪 测试

运行测试：
```bash
python -m pytest tests/
```

测试覆盖：
- API 端点测试
- 工具函数测试
- 子代理功能测试

## 🚀 快速开始

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 初始化数据库：
```bash
python src/database/init_db.py
```

3. 启动服务：
```bash
python src/api/app.py
```

## 📖 更多文档

详细文档请查看 `readme/` 目录：
- [README08.md](readme/README08.md) - 基础说明
- [README09.md](readme/README09.md) - 进阶功能
- [README10.md](readme/README10.md) - 实现细节
- [README11.md](readme/README11.md) - 高级特性
- [README12.md](readme/README12.md) - 最新更新

## 📄 许可证

MIT License