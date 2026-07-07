---
name: example-skill
description: 一个示例技能，展示如何编写 skill
tags:
  - example
  - demo
---

# 示例技能 (Example Skill)

这是一个示例技能，用于展示如何创建和使用 skill。

## 功能说明

这个技能可以：
1. 展示 skill 的基本结构
2. 提供代码模板
3. 帮助用户理解 skill 的工作原理

## 使用方法

当你需要创建新的 skill 时，可以参考这个示例：

```
skills/
└── your-skill-name/
    └── SKILL.md
```

## 示例代码

### Python 代码示例

```python
def hello_world():
    """打印 Hello World"""
    print("Hello, World!")
    return "Success"

if __name__ == "__main__":
    hello_world()
```

### Shell 命令示例

```bash
# 列出当前目录文件
ls -la

# 查看文件内容
cat filename.txt
```

## 注意事项

- Skill 文件夹名称建议使用小写字母和连字符
- SKILL.md 是必须的文件名
- frontmatter 中的 name 和 description 是必填字段

## 扩展阅读

更多关于 skill 的信息，请参考项目文档。