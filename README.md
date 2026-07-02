# Quanters' Gate 3

## 如何参与项目

### 连接 GitHub 仓库

在本地项目文件夹中运行

`git clone https://github.com/cleverpigeb/Quanters-Gate-3.git`

以克隆远程仓库，完成初始化

以下为修改、推送流程

```
# 新建分支
git switch -c <分支名>

# 拉取远程更新内容
git pull origin main

# 将本地修改添加至缓冲区
git add .

# 提交缓冲区内容
git commit -m "提交说明"

# 将本地修改提交至云端
git push origin <分支名>

# （合并分支后）删除本地分支
git switch main
git branch -d <分支名>

# 删除远程分支
git push origin :<分支名>
```

### 使用 UV 进行包管理

克隆仓库后，在项目文件夹中运行

`uv sync`

可自动完成环境同步，包括项目依赖等等

其他内容待补充……