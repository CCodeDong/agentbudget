# Git / GitHub 同步指南（零基础版）


> ⚠️ **本文件已脱敏**：仓库公开后，文中真实邮箱与 GitCode 身份已替换为占位符。
> 你自己配置时请填真实值。

> 你从没用过 Git。这份文档从"装好之后第一件事"讲起，每一步都有**命令 + 预期输出**。
> 照着做即可，不需要理解原理。
>
> 最后更新：2026-09

---

## 0. 现在的状态 —— **已经全部完成，可以直接用了**

2026-09 更新：仓库已建立并成功推送。**队友直接跳到第 6 节「克隆」即可。**

| 项目 | 状态 |
|---|---|
| Git 安装 | ✅ `git version 2.53.0.windows.1` |
| 本地仓库 | ✅ `C:\Users\86178\Documents\deepseek-harness\Project\.git` |
| 忽略规则 | ✅ `.gitignore` 已写好，排除约 60 MB 构建缓存 |
| Git 身份 | ✅ `你的用户名 <你的 GitHub 邮箱>`（**仓库级**，见下方说明） |
| 首次提交 | ✅ `51d9037`，213 文件 / 16.4 MB |
| 分支名 | ✅ `main`（已与 GitHub 默认一致） |
| 远程地址 | ✅ `https://github.com/CCodeDong/agentbudget.git` |
| **推送** | ✅ **已完成，本地与远程 commit 完全一致** |
| 认证 | ✅ 无需操作（本机 Git 凭据管理器已有缓存凭据） |

### ⚠️ 三个与原计划不同之处，需要知道

**① Git 身份设在了「仓库级」而不是「全局级」**

原计划用 `git config --global`，但当前环境的沙箱不允许写全局配置文件
（`C:\Users\86178\.gitconfig` 报 `Permission denied`）。改为**只对本仓库生效**：

```powershell
cd C:\Users\86178\Documents\deepseek-harness\Project
git config user.name  "CCodeDong"
git config user.email "你的GitHub邮箱"
```

**这反而更好**：你的全局身份仍是 GitCode 的（`你的GitCode身份@noreply.gitcode.com`），
如果之后要参加开源鸿蒙大赛往 GitCode 推代码，两套身份互不干扰。

> 若将来想让全局也改成 GitHub 身份，在**你自己的、非受限的** PowerShell 里跑：
> ```powershell
> git config --global user.name "CCodeDong"
> git config --global user.email "你的GitHub邮箱"
> ```
> 注意邮箱**不要带多余空格**。

**② 第 4 节（登录 / token）可以跳过**

推送时没有要求输入任何凭据——本机 Git 凭据管理器（Git Credential Manager）
已缓存 GitHub 凭据。**如果以后换电脑或凭据失效**，再回来看第 4 节。

**③ 顺带发现：hosts 文件里有屏蔽规则**

你的 `C:\Windows\System32\drivers\etc\hosts` 有 **50 条**把站点指向 `127.0.0.1` 的规则，
包括 `github.com`、`api.github.com`、`huggingface.co`、`store.steampowered.com` 等。

**实测 git 访问 GitHub 正常**，所以这不影响本项目。
但这说明这台机器装过某种屏蔽工具，**如果以后 GitHub 时通时不通，先怀疑这里**。
修改需要管理员权限。

---

## 1. 改 Git 身份（**已完成，保留供参考**）


你电脑上现在的 Git 身份是 **GitCode** 的：

```
user.name  : 你的GitCode用户名
user.email : 你的GitCode身份@noreply.gitcode.com
```

**如果不改，你推到 GitHub 的提交会显示成一个陌生名字，且不会算到你的 GitHub 账号上。**

改成你的 GitHub 邮箱（就是注册 GitHub 用的那个）：

```powershell
git config --global user.name "你的GitHub用户名"
git config --global user.email "你的GitHub邮箱"
```

验证：

```powershell
git config --global user.name
git config --global user.email
```

**然后要把已有的那一次提交也改成你的名字**（否则第一条记录还是旧的）：

```powershell
cd C:\Users\86178\Documents\deepseek-harness\Project
git commit --amend --reset-author --no-edit
```

> ⚠️ 这一步**必须在推送到 GitHub 之前**做。推上去之后再改会麻烦很多。

---

## 2. 在 GitHub 上创建仓库

1. 登录 [github.com](https://github.com)
2. 右上角 **`+`** → **New repository**
3. 填写：

| 字段 | 填什么 |
|---|---|
| Repository name | `agentbudget`（或你喜欢的名字，**建议全英文**） |
| Description | `端侧多智能体预算调度：仓颉调度器库 + HarmonyOS 应用` |
| **Public / Private** | **选 Private** ✅ |

> **为什么建议 Private**：这是课程作业，包含你的学号、姓名、报告全文。
> 而且**答辩前不应该公开**。Private 仓库可以免费邀请最多 3 人协作（我们正好够）。
> 等课程结束后想公开再改。

4. **下面三个勾选框全部不要勾**（Add README / .gitignore / license）
   —— 因为本地已经有这些文件了，勾了会造成冲突。
5. 点 **Create repository**

创建后会看到一个空仓库页面，上面有一段 `git remote add origin ...` —— **第 3 步要用到它**。

---

## 3. 把本地仓库连到 GitHub

### 3.1 分支改名 master → main

GitHub 默认分支叫 `main`，本地是 `master`。先统一：

```powershell
cd C:\Users\86178\Documents\deepseek-harness\Project
git branch -M main
```

（`-M` 是"强制重命名"，不会有输出，正常。）

### 3.2 添加远程地址

在 GitHub 仓库页面上复制那行 HTTPS 地址（形如 `https://github.com/你的用户名/agentbudget.git`），然后：

```powershell
git remote add origin https://github.com/你的用户名/agentbudget.git
```

验证：

```powershell
git remote -v
```

预期输出（两行，`fetch` 和 `push`）：

```
origin  https://github.com/你的用户名/agentbudget.git (fetch)
origin  https://github.com/你的用户名/agentbudget.git (push)
```

### 3.3 推送

```powershell
git push -u origin main
```

**这里会弹出登录窗口——见下一节。**

---

## 4. 解决登录问题（新手最容易卡住的地方）

GitHub 从 2021 年起**不再接受账号密码**。你有两条路，选一条即可。

### 方案 A：Personal Access Token（推荐，配置最快）

1. GitHub 右上角头像 → **Settings**
2. 左侧最下 → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)**
4. **Generate new token** → **Generate new token (classic)**
5. 填写：
   - Note：`课程项目`（随便写）
   - Expiration：**选 90 天**或更长
   - **勾选 `repo`**（这一项必须勾，它包含读写仓库的权限）
6. 点最下面 **Generate token**
7. **立刻复制那串字符**（形如 `ghp_xxxxxxxxxxxx`）

> ⚠️ **这串 token 只显示一次**，关掉页面就再也看不到了。先粘到记事本里。

然后推送：

```powershell
git push -u origin main
```

弹出登录窗口时：
- **Username**：你的 GitHub 用户名
- **Password**：**粘贴那串 token**（不是你的登录密码！）

成功后会显示进度条，最后类似：

```
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

**以后就不用再输了**（Windows 会记住凭据）。

### 方案 B：SSH 密钥（一次配置，永不失效）

如果嫌 token 会过期，可以配 SSH：

```powershell
# 1. 生成密钥（一路回车，密码可留空）
ssh-keygen -t ed25519 -C "你的GitHub邮箱"

# 2. 复制公钥内容
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | Set-Clipboard
```

然后：GitHub → Settings → **SSH and GPG keys** → **New SSH key** → 粘贴 → Add。

最后把远程地址换成 SSH 形式：

```powershell
git remote set-url origin git@github.com:你的用户名/agentbudget.git
git push -u origin main
```

> 验证连接：`ssh -T git@github.com`，出现 `Hi 用户名!` 就对了。

### 方案 C：GitHub Desktop（完全不用命令行）

如果命令行让你不适，可以下载 [GitHub Desktop](https://desktop.github.com/)，
登录后选 **File → Add local repository**，指向
`C:\Users\86178\Documents\deepseek-harness\Project`，然后点 **Publish repository**。

图形界面会处理所有登录问题。**后续日常操作也可以在它里面点按钮完成。**

---

## 5. 邀请队友

1. GitHub 仓库页面 → **Settings** → 左侧 **Collaborators**
2. 点 **Add people**
3. 输入队友的 GitHub 用户名或邮箱
4. 队友会收到邮件，**必须点邮件里的链接接受邀请**（不点的话没有权限）

> Private 仓库免费版最多 3 人协作（含你自己），我们这门课够用。

---

## 6. 队友怎么拿到代码

把仓库地址发给队友。他们需要：

```powershell
# 1. 安装 Git（如果没装）：https://git-scm.com/download/win
# 2. 配置身份
git config --global user.name "他的用户名"
git config --global user.email "他的邮箱"

# 3. 克隆
cd D:\某个你放代码的地方
git clone https://github.com/你的用户名/agentbudget.git

# 4. 进入项目
cd agentbudget
```

首次 `git push` 时同样需要用 token（见第 4 节方案 A）。

---

## 7. 日常怎么用（**最常用的一节**）

### 每次开始工作前：先拉取

```powershell
cd C:\Users\86178\Documents\deepseek-harness\Project
git pull
```

**这一步不能省。** 队友改过的内容要先同步下来，否则会冲突。

### 改完之后：三连

```powershell
git status              # 1. 看改了哪些文件（红色=未添加，绿色=已添加）
git add -A              # 2. 把所有改动加入暂存区
git commit -m "说明你改了什么"   # 3. 提交到本地
git push                # 4. 推到 GitHub
```

**`commit -m` 后面的说明要写人话**，比如：

- ✅ `补充答辩 PPT 第 12 页的实验数据`
- ✅ `修正报告里的覆盖率数字`
- ❌ `update`
- ❌ `改了一下`

好的提交说明在出问题时能救命——你可以随时回到任何一个历史版本。

### 只想提交部分文件

```powershell
git add 报告.docx 图片.png     # 只添加这两个
git commit -m "更新报告与配图"
git push
```

---

## 8. 出问题了怎么办

### 情况 1：`git push` 被拒绝，提示 `rejected` / `fetch first`

**原因**：队友先推了东西，你本地落后了。

```powershell
git pull            # 先拉下来
git push            # 再推
```

### 情况 2：`git pull` 提示冲突（conflict）

**原因**：你和队友改了**同一个文件的同一处**。

打开冲突的文件，会看到这样的标记：

```
<<<<<<< HEAD
你写的内容
=======
队友写的内容
>>>>>>> origin/main
```

**手动改成你想要的样子**（把 `<<<<<<<`、`=======`、`>>>>>>>` 三行删掉，保留正确内容），然后：

```powershell
git add -A
git commit -m "解决冲突"
git push
```

> 如果搞乱了想放弃这次合并：`git merge --abort`

### 情况 3：提交了不该提交的文件（比如构建缓存）

先把它加进 `.gitignore`，然后：

```powershell
git rm -r --cached 那个文件夹
git commit -m "移除不该纳入版本控制的文件"
```

（`--cached` 表示"只从 git 里移除，不删本地文件"——**千万别漏了它**，否则会删掉你磁盘上的文件。）

### 情况 4：想撤销刚才的提交（但保留文件改动）

```powershell
git reset --soft HEAD~1
```

### 情况 5：想看看历史

```powershell
git log --oneline          # 简版，一行一条
git log --oneline --graph  # 带分支图
git show HEAD              # 看最近一次提交改了什么
```

### 情况 6：彻底搞乱了，想重新来

**先别慌，也别删 `.git`。** 把 `git status` 的输出发给我，我告诉你怎么恢复。

---

## 9. 三个注意点

### 9.1 签名证书已被排除

`.gitignore` 里已经写了 `*.p12` / `*.p7b` / `*.cer`。
**这些是签名材料，绝不能上传到 GitHub**——即使是 Private 仓库也不应该。

### 9.2 大文件不会进仓库

以下目录已被排除，**不会**上传（合计约 60 MB）：

| 目录 | 体积 | 为什么排除 |
|---|---|---|
| `projects/agentbudget4cj/target/` | 34 MB | 构建缓存，可重建 |
| `app/harmony/_hvhome/` | 17 MB | hvigor 缓存 |
| `app/harmony/_npmcache/` | 9 MB | npm 缓存 |
| `stdx/` | 18 MB | 仓颉扩展库副本，本项目不依赖（已实测） |
| `_research/` | 0.5 MB | 一个无关的网页小游戏 |

> **注意**：`projects/agentbudget4cj/bin/agentbudget4cj.exe`（11.2 MB）**是包含在内的**，
> 因为它是课程要求的可运行产物，队友克隆后能直接跑演示。
> 如果你后面频繁重建它导致仓库变大，可以在 `.gitignore` 里取消那行的注释。

### 9.3 中文文件名没问题

已经设置了 `core.quotepath false`，中文文件名会正常显示，不会变成乱码转义。

---

## 10. 一页速查

```powershell
# ---- 每天开始 ----
cd C:\Users\86178\Documents\deepseek-harness\Project
git pull

# ---- 每天结束 ----
git status
git add -A
git commit -m "写清楚你改了什么"
git push

# ---- 看看发生了什么 ----
git log --oneline -10
git diff                    # 还没 add 的改动
git diff --cached           # 已 add 待提交的改动

# ---- 后悔药 ----
git reset --soft HEAD~1     # 撤销上次提交，保留改动
git checkout -- 文件名       # 丢弃某文件未提交的改动
git restore 文件名           # 同上（新语法）
```

---

## 11. 现在按顺序做这五件事

1. **改 Git 身份**（第 1 节）→ 两个 `git config` + 一个 `--amend`
2. **在 GitHub 建 Private 仓库**（第 2 节）
3. **连远程并推送**（第 3 节）→ `git branch -M main`、`git remote add`、`git push`
4. **遇到登录就建 token**（第 4 节方案 A）
5. **邀请队友**（第 5 节）

**卡在哪一步就把那一步的报错原文发给我**，我告诉你怎么办。
